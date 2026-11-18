"""Casos de uso do MVP. Toda operação recebe um Contexto já autorizado,
checa a permissão da ação, grava em transação e registra no audit_log.
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from domain import deduplicator, reconciler, risk_evaluator, rules_engine
from domain.money import formatar_br
from exporters import fortes_exporter
from exporters.fortes_exporter import ContaPlano, LoteBloqueado
from parsers import fortes_plano_parser, fortes_razao_parser, ofx_parser, tabular_parser
from parsers.comum import ErroEstrutural, sanitizar_texto
from storage import audit, cripto
from storage.database import agora, conectar_empresa, definir_parametro, parametro, pasta_empresa, transacao
from storage.usuarios import abrir_empresa_autorizada, exigir

NATUREZAS = ("normal", "transferencia", "tributo", "socio", "incerta")


class OperacaoInvalida(ValueError):
    pass


@dataclass
class Contexto:
    central: sqlite3.Connection
    usuario: sqlite3.Row
    empresa: sqlite3.Row
    con: sqlite3.Connection
    data_dir: Path | None = None

    @classmethod
    def abrir(cls, central, usuario, slug, data_dir=None) -> "Contexto":
        emp, con = abrir_empresa_autorizada(central, usuario["id"], slug, data_dir)
        return cls(central, usuario, emp, con, data_dir)

    @property
    def nome(self) -> str:
        """Identidade gravada em toda ação. Inclui o id: dois usuários com o mesmo nome não se confundem
        (a segregação de função compara este valor)."""
        return f"{self.usuario['nome']} #{self.usuario['id']}"

    def exigir(self, acao: str) -> None:
        exigir(self.central, self.usuario["id"], self.empresa["id"], acao)

    @property
    def pasta(self) -> Path:
        return pasta_empresa(self.empresa["slug"], self.data_dir)

    @property
    def prefixo(self) -> str:
        padrao = re.sub(r"[^A-Z0-9]", "", self.empresa["slug"].upper())[:6] or "EXT"
        if len(padrao) < 2 or padrao in fortes_exporter.PREFIXOS_RESERVADOS:
            padrao = "EXT"
        return parametro(self.con, "prefixo_marca", padrao)

    def gravar_arquivo(self, destino: Path, bruto: bytes) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(cripto.proteger(self.empresa["slug"], bruto))
        os.chmod(destino, 0o444)

    def ler_arquivo(self, destino: Path) -> bytes:
        return cripto.recuperar(self.empresa["slug"], destino.read_bytes())


# ---------------------------------------------------------------- arquivos

def _guardar_original(ctx: Contexto, nome: str, bruto: bytes, tipo: str, hash_hex: str) -> int:
    uid = uuid.uuid4().hex
    ext = Path(nome).suffix.lower()[:6]
    destino = ctx.pasta / "arquivos" / "originais" / f"{uid}{ext}"
    ctx.gravar_arquivo(destino, bruto)  # só leitura e, se a chave estiver configurada, cifrado
    cur = ctx.con.execute(
        "INSERT INTO arquivos (uuid, nome_original, tipo, sha256, tamanho, caminho, enviado_por, enviado_em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (uid, sanitizar_texto(nome), tipo, hash_hex, len(bruto), str(destino.relative_to(ctx.pasta)),
         ctx.nome, agora()),
    )
    return cur.lastrowid


def _bloquear_repetido(ctx: Contexto, hash_hex: str, nome: str) -> None:
    rep = deduplicator.arquivo_repetido(ctx.con, hash_hex)
    if rep:
        audit.registrar(ctx.con, ctx.nome, "carga_bloqueada_arquivo_repetido", "arquivo", rep["id"], nome=nome)
        raise ErroEstrutural([
            f"arquivo idêntico (SHA-256) já carregado em {rep['enviado_em']} por {rep['enviado_por']} "
            f"como '{rep['nome_original']}'"
        ])


# ---------------------------------------------------------------- plano de contas

def carregar_plano(ctx: Contexto, nome: str, bruto: bytes) -> dict:
    ctx.exigir("cadastrar")
    contas = fortes_plano_parser.ler_plano_fortes(bruto)
    h = deduplicator.sha256(bruto)
    with transacao(ctx.con):
        arq = _guardar_original(ctx, nome, bruto, "plano_contas", h)
        versao = (ctx.con.execute("SELECT COALESCE(MAX(versao), 0) FROM plano_contas").fetchone()[0]) + 1
        ctx.con.execute("UPDATE plano_contas SET vigente = 0 WHERE vigente = 1")
        ctx.con.executemany(
            "INSERT INTO plano_contas (versao, classificacao, descricao, reduzido, aceita_lancamento, natureza, "
            "vigente, arquivo_id) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            [(versao, c["classificacao"], c["descricao"], c["reduzido"], c["aceita_lancamento"], c["natureza"], arq)
             for c in contas],
        )
        analiticas = sum(c["aceita_lancamento"] for c in contas)
        audit.registrar(ctx.con, ctx.nome, "plano_importado", "plano_contas", versao,
                        contas=len(contas), analiticas=analiticas, arquivo=nome)
    return {"versao": versao, "contas": len(contas), "analiticas": analiticas}


def plano_vigente(con: sqlite3.Connection) -> dict[str, ContaPlano]:
    linhas = con.execute(
        "SELECT reduzido, classificacao, descricao, aceita_lancamento FROM plano_contas "
        "WHERE vigente = 1 AND reduzido IS NOT NULL"
    ).fetchall()
    return {l["reduzido"]: ContaPlano(l["reduzido"], l["classificacao"], l["descricao"], bool(l["aceita_lancamento"]))
            for l in linhas}


def contas_analiticas(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT reduzido, classificacao, descricao FROM plano_contas WHERE vigente = 1 AND aceita_lancamento = 1 "
        "ORDER BY classificacao"
    ).fetchall()


def _exigir_conta_valida(con: sqlite3.Connection, reduzido: str, papel: str) -> None:
    plano = plano_vigente(con)
    if not plano:
        raise OperacaoInvalida("importe o plano de contas do Fortes antes")
    c = plano.get(str(reduzido))
    if c is None:
        raise OperacaoInvalida(f"{papel}: conta {reduzido} não existe no plano vigente")
    if not c.aceita_lancamento:
        raise OperacaoInvalida(f"{papel}: conta {reduzido} não aceita lançamento")


# ---------------------------------------------------------------- regras e sócios

def _regras(con) -> list[rules_engine.Regra]:
    return [rules_engine.Regra(
        id=r["id"], prioridade=r["prioridade"], nome=r["nome"], tipo_padrao=r["tipo_padrao"], padrao=r["padrao"],
        sentido=r["sentido"], conta_contrapartida=r["conta_contrapartida"], historico=r["historico"],
        natureza=r["natureza"], valor_min_centavos=r["valor_min_centavos"], valor_max_centavos=r["valor_max_centavos"],
    ) for r in con.execute("SELECT * FROM regras WHERE ativa = 1").fetchall()]


def criar_regra(ctx: Contexto, nome: str, tipo_padrao: str, padrao: str, sentido: str, conta: str,
                prioridade: int = 100, historico: str | None = None, natureza: str = "normal",
                valor_min_centavos: int | None = None, valor_max_centavos: int | None = None,
                evidencia: str | None = None) -> int:
    ctx.exigir("cadastrar")
    if not padrao.strip():
        raise OperacaoInvalida("padrão vazio")
    if tipo_padrao == "regex":
        rules_engine.validar_regex(padrao)
    if natureza not in NATUREZAS:
        raise OperacaoInvalida(f"natureza inválida: {natureza}")
    _exigir_conta_valida(ctx.con, conta, "contrapartida da regra")
    with transacao(ctx.con):
        cur = ctx.con.execute(
            "INSERT INTO regras (prioridade, nome, tipo_padrao, padrao, sentido, valor_min_centavos, "
            "valor_max_centavos, conta_contrapartida, historico, natureza, criada_por, criada_em, evidencia) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(prioridade), nome.strip() or padrao[:40], tipo_padrao, padrao, sentido, valor_min_centavos,
             valor_max_centavos, str(conta), historico or None, natureza, ctx.nome, agora(), evidencia),
        )
        audit.registrar(ctx.con, ctx.nome, "regra_criada", "regra", cur.lastrowid, padrao=padrao, conta=conta)
    return cur.lastrowid


def desativar_regra(ctx: Contexto, regra_id: int) -> None:
    ctx.exigir("cadastrar")
    with transacao(ctx.con):
        ctx.con.execute("UPDATE regras SET ativa = 0 WHERE id = ?", (regra_id,))
        audit.registrar(ctx.con, ctx.nome, "regra_desativada", "regra", regra_id)


def importar_regras_json(ctx: Contexto, bruto: bytes) -> dict:
    """Importa regras no formato {"regras": [{"padrao", "sentido", "conta", "historico", "evidencia"}]}.
    `conta` pode ser o reduzido ou a classificação; a classificação é convertida pelo plano vigente."""
    ctx.exigir("cadastrar")
    try:
        dados = json.loads(bruto.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErroEstrutural([f"JSON inválido: {exc}"]) from exc
    por_class = {l["classificacao"]: l["reduzido"] for l in contas_analiticas(ctx.con)}
    plano = plano_vigente(ctx.con)
    criadas, ignoradas = 0, []
    for i, r in enumerate(dados.get("regras", []), start=1):
        conta = str(r.get("conta", ""))
        red = conta if conta in plano else por_class.get(conta)
        if not red:
            ignoradas.append(f"regra {r.get('id', i)}: conta {conta} não está no plano vigente")
            continue
        sentido = r.get("sentido", "ambos")
        if sentido not in ("entrada", "saida", "ambos"):
            ignoradas.append(f"regra {r.get('id', i)}: sentido inválido {sentido!r}")
            continue
        try:
            criar_regra(ctx, nome=str(r.get("id", f"json-{i}")), tipo_padrao="regex", padrao=r["padrao"],
                        sentido=sentido, conta=red, prioridade=int(r.get("prioridade", 100)),
                        historico=r.get("historico"), evidencia=r.get("evidencia"))
            criadas += 1
        except (ValueError, KeyError) as exc:
            ignoradas.append(f"regra {r.get('id', i)}: {exc}")
    return {"criadas": criadas, "ignoradas": ignoradas}


def termos_socios(con) -> list[str]:
    return [r["termo"] for r in con.execute("SELECT termo FROM socios ORDER BY termo").fetchall()]


def adicionar_socio(ctx: Contexto, termo: str) -> None:
    ctx.exigir("cadastrar")
    termo = sanitizar_texto(termo)
    if len(termo) < 3:
        raise OperacaoInvalida("informe ao menos 3 caracteres do nome do sócio")
    with transacao(ctx.con):
        ctx.con.execute("INSERT OR IGNORE INTO socios (termo) VALUES (?)", (termo,))
        audit.registrar(ctx.con, ctx.nome, "socio_cadastrado", "socio", None, termo=termo)


def remover_socio(ctx: Contexto, termo: str) -> None:
    ctx.exigir("cadastrar")
    with transacao(ctx.con):
        ctx.con.execute("DELETE FROM socios WHERE termo = ?", (termo,))
        audit.registrar(ctx.con, ctx.nome, "socio_removido", "socio", None, termo=termo)


# ---------------------------------------------------------------- carga de extratos

def _avaliar_risco(ctx: Contexto, mov: sqlite3.Row | dict) -> list[str]:
    return risk_evaluator.avaliar(
        mov["valor_centavos"], mov["historico"], mov["natureza"], mov["decisao_duplicidade"],
        ctx.empresa["limite_revisao_centavos"], termos_socios(ctx.con),
    )


def _propor(ctx: Contexto, mov_id: int, regras: list[rules_engine.Regra]) -> bool:
    m = ctx.con.execute("SELECT * FROM movimentos WHERE id = ?", (mov_id,)).fetchone()
    r = rules_engine.encontrar(regras, m["historico"], m["valor_centavos"])
    if r is None:
        return False
    deb, cred = rules_engine.partidas(m["valor_centavos"], m["conta_banco"], r.conta_contrapartida)
    ctx.con.execute(
        "UPDATE movimentos SET status = 'proposto', conta_debito = ?, conta_credito = ?, historico_contabil = ?, "
        "regra_id = ?, origem_classificacao = 'regra', natureza = ? WHERE id = ?",
        (deb, cred, r.historico or m["historico"], r.id, r.natureza, mov_id),
    )
    return True


def _atualizar_risco(ctx: Contexto, mov_id: int) -> list[str]:
    m = ctx.con.execute("SELECT * FROM movimentos WHERE id = ?", (mov_id,)).fetchone()
    motivos = _avaliar_risco(ctx, m)
    ctx.con.execute("UPDATE movimentos SET exige_segunda_confirmacao = ?, motivos_risco = ? WHERE id = ?",
                    (1 if motivos else 0, "; ".join(motivos) or None, mov_id))
    return motivos


def carregar_extrato(ctx: Contexto, nome: str, bruto: bytes, conta_banco: str,
                     mapa: tabular_parser.Mapeamento | None = None) -> dict:
    ctx.exigir("carregar")
    _exigir_conta_valida(ctx.con, conta_banco, "conta do banco")
    h = deduplicator.sha256(bruto)
    _bloquear_repetido(ctx, h, nome)
    extrato = None
    if nome.lower().endswith(".ofx"):
        extrato = ofx_parser.ler_ofx(bruto)
        movs, tipo = extrato.movimentos, "extrato_ofx"
    else:
        if mapa is None:
            raise OperacaoInvalida("informe o mapeamento das colunas")
        _, linhas = tabular_parser.ler_tabela(bruto, nome)
        movs, tipo = tabular_parser.extrair_movimentos(linhas, mapa), "extrato_tabular"
    regras = _regras(ctx.con)
    resumo = {"movimentos": 0, "propostos": 0, "alertas_duplicidade": 0, "segunda_revisao": 0,
              "periodo": (min(m["data"] for m in movs), max(m["data"] for m in movs)),
              "saldo_final_ofx": extrato.saldo_final_centavos if extrato else None,
              "saldo_data_ofx": extrato.saldo_data if extrato else None}
    with transacao(ctx.con):
        arq = _guardar_original(ctx, nome, bruto, tipo, h)
        for m in movs:
            dup = deduplicator.procurar(ctx.con, m, conta_banco, arq)
            cur = ctx.con.execute(
                "INSERT INTO movimentos (arquivo_id, linha_origem, data, valor_centavos, historico, documento, fitid, "
                "conta_banco, decisao_duplicidade, duplicidade_de, motivo_duplicidade) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (arq, m["linha"], m["data"], m["valor_centavos"], m["historico"], m["documento"], m["fitid"],
                 conta_banco, "pendente" if dup else "nao_aplica", dup[0] if dup else None, dup[1] if dup else None),
            )
            mid = cur.lastrowid
            resumo["movimentos"] += 1
            resumo["alertas_duplicidade"] += bool(dup)
            resumo["propostos"] += _propor(ctx, mid, regras)
            resumo["segunda_revisao"] += bool(_atualizar_risco(ctx, mid))
        audit.registrar(ctx.con, ctx.nome, "extrato_carregado", "arquivo", arq, nome=nome, sha256=h,
                        **{k: v for k, v in resumo.items() if k != "periodo"})
    return resumo


def carregar_planilha_despesas(ctx: Contexto, nome: str, bruto: bytes, mapa: tabular_parser.Mapeamento) -> dict:
    """Planilha auxiliar: não gera lançamento; serve para identificar SISPAG/PIX sem nome."""
    ctx.exigir("carregar")
    h = deduplicator.sha256(bruto)
    _bloquear_repetido(ctx, h, nome)
    _, linhas = tabular_parser.ler_tabela(bruto, nome)
    itens = tabular_parser.extrair_movimentos(linhas, mapa)
    with transacao(ctx.con):
        arq = _guardar_original(ctx, nome, bruto, "planilha_despesas", h)
        ctx.con.executemany(
            "INSERT INTO despesas_planilha (arquivo_id, linha_origem, data, valor_centavos, descricao, "
            "lancamento_bancario) VALUES (?, ?, ?, ?, ?, ?)",
            [(arq, i["linha"], i["data"], i["valor_centavos"], i["historico"], i["documento"]) for i in itens],
        )
        audit.registrar(ctx.con, ctx.nome, "planilha_despesas_carregada", "arquivo", arq, nome=nome, itens=len(itens))
    return {"itens": len(itens)}


def pistas_planilha(con, mov: sqlite3.Row, janela_dias: int | None = None) -> list[sqlite3.Row]:
    import config
    j = config.JANELA_PLANILHA_DIAS if janela_dias is None else janela_dias
    return con.execute(
        "SELECT * FROM despesas_planilha WHERE ABS(valor_centavos) = ABS(?) "
        "AND ABS(julianday(data) - julianday(?)) <= ? ORDER BY ABS(julianday(data) - julianday(?))",
        (mov["valor_centavos"], mov["data"], j, mov["data"]),
    ).fetchall()


def reaplicar_regras(ctx: Contexto) -> int:
    ctx.exigir("classificar")
    regras = _regras(ctx.con)
    n = 0
    with transacao(ctx.con):
        for m in ctx.con.execute("SELECT id FROM movimentos WHERE status = 'pendente'").fetchall():
            if _propor(ctx, m["id"], regras):
                _atualizar_risco(ctx, m["id"])
                n += 1
        audit.registrar(ctx.con, ctx.nome, "regras_reaplicadas", "movimento", None, propostos=n)
    return n


# ---------------------------------------------------------------- fila de classificação

def _mov(ctx: Contexto, mov_id: int) -> sqlite3.Row:
    m = ctx.con.execute("SELECT * FROM movimentos WHERE id = ?", (mov_id,)).fetchone()
    if m is None:
        raise OperacaoInvalida(f"movimento {mov_id} não existe nesta empresa")
    return m


def classificar(ctx: Contexto, mov_id: int, contrapartida: str, historico: str | None = None,
                natureza: str = "normal", origem: str = "manual") -> list[str]:
    """Revisão inicial. Vale para aceitar proposta de regra, sugestão de IA ou classificação manual."""
    ctx.exigir("classificar")
    if natureza not in NATUREZAS:
        raise OperacaoInvalida(f"natureza inválida: {natureza}")
    if origem not in ("regra", "manual", "ia"):
        raise OperacaoInvalida("origem inválida")
    _exigir_conta_valida(ctx.con, contrapartida, "contrapartida")
    with transacao(ctx.con):
        m = _mov(ctx, mov_id)
        if m["status"] in ("exportado", "descartado"):
            raise OperacaoInvalida(f"movimento {mov_id} está {m['status']} e não pode ser alterado")
        if str(contrapartida) == m["conta_banco"]:
            raise OperacaoInvalida("a contrapartida não pode ser a própria conta do banco")
        deb, cred = rules_engine.partidas(m["valor_centavos"], m["conta_banco"], str(contrapartida))
        ctx.con.execute(
            "UPDATE movimentos SET status = 'classificado', conta_debito = ?, conta_credito = ?, historico_contabil = ?, "
            "natureza = ?, origem_classificacao = ?, regra_id = CASE WHEN ? = 'regra' THEN regra_id ELSE NULL END, "
            "revisado_por = ?, revisado_em = ?, segunda_confirmacao_por = NULL, segunda_confirmacao_em = NULL "
            "WHERE id = ?",
            (deb, cred, sanitizar_texto(historico) or m["historico_contabil"] or m["historico"], natureza, origem,
             origem, ctx.nome, agora(), mov_id),
        )
        motivos = _atualizar_risco(ctx, mov_id)
        audit.registrar(ctx.con, ctx.nome, "movimento_classificado", "movimento", mov_id, debito=deb, credito=cred,
                        natureza=natureza, origem=origem, segunda_revisao=motivos)
    return motivos


def segunda_confirmacao(ctx: Contexto, mov_id: int) -> None:
    ctx.exigir("segunda_confirmacao")
    with transacao(ctx.con):
        m = _mov(ctx, mov_id)
        if m["status"] != "classificado" or not m["exige_segunda_confirmacao"]:
            raise OperacaoInvalida("movimento não está aguardando segunda confirmação")
        if m["revisado_por"] == ctx.nome:
            audit.registrar(ctx.con, ctx.nome, "segunda_confirmacao_negada_mesmo_usuario", "movimento", mov_id)
            raise OperacaoInvalida("quem fez a revisão inicial não pode dar a segunda confirmação")
        if m["segunda_confirmacao_por"]:
            raise OperacaoInvalida("movimento já confirmado")
        ctx.con.execute("UPDATE movimentos SET segunda_confirmacao_por = ?, segunda_confirmacao_em = ? WHERE id = ?",
                        (ctx.nome, agora(), mov_id))
        audit.registrar(ctx.con, ctx.nome, "segunda_confirmacao", "movimento", mov_id, revisado_por=m["revisado_por"])


def devolver(ctx: Contexto, mov_id: int, motivo: str) -> None:
    """Segunda revisão discorda: volta para a fila com o motivo."""
    ctx.exigir("segunda_confirmacao")
    if not motivo.strip():
        raise OperacaoInvalida("informe o motivo da devolução")
    with transacao(ctx.con):
        m = _mov(ctx, mov_id)
        if m["status"] != "classificado":
            raise OperacaoInvalida("só um movimento classificado pode ser devolvido")
        ctx.con.execute(
            "UPDATE movimentos SET status = 'pendente', revisado_por = NULL, revisado_em = NULL, "
            "segunda_confirmacao_por = NULL, segunda_confirmacao_em = NULL, observacao = ? WHERE id = ?",
            (f"Devolvido por {ctx.nome}: {sanitizar_texto(motivo)}", mov_id),
        )
        audit.registrar(ctx.con, ctx.nome, "movimento_devolvido", "movimento", mov_id, motivo=motivo)


def colocar_em_espera(ctx: Contexto, mov_id: int, motivo: str) -> None:
    ctx.exigir("classificar")
    if not motivo.strip():
        raise OperacaoInvalida("informe o que falta para classificar")
    with transacao(ctx.con):
        m = _mov(ctx, mov_id)
        if m["status"] in ("exportado", "descartado"):
            raise OperacaoInvalida(f"movimento {m['status']}")
        ctx.con.execute("UPDATE movimentos SET status = 'em_espera', observacao = ? WHERE id = ?",
                        (sanitizar_texto(motivo), mov_id))
        audit.registrar(ctx.con, ctx.nome, "movimento_em_espera", "movimento", mov_id, motivo=motivo)


def retomar(ctx: Contexto, mov_id: int) -> None:
    ctx.exigir("classificar")
    with transacao(ctx.con):
        m = _mov(ctx, mov_id)
        if m["status"] != "em_espera":
            raise OperacaoInvalida("movimento não está em espera")
        novo = "proposto" if m["origem_classificacao"] == "regra" and not m["revisado_por"] else (
            "classificado" if m["revisado_por"] else "pendente")
        ctx.con.execute("UPDATE movimentos SET status = ? WHERE id = ?", (novo, mov_id))
        audit.registrar(ctx.con, ctx.nome, "movimento_retomado", "movimento", mov_id, status=novo)


def decidir_duplicidade(ctx: Contexto, mov_id: int, decisao: str, justificativa: str) -> None:
    ctx.exigir("decidir_duplicidade")
    if decisao not in ("manter", "descartar"):
        raise OperacaoInvalida("decisão deve ser 'manter' ou 'descartar'")
    if not justificativa.strip():
        raise OperacaoInvalida("registre o porquê da decisão")
    with transacao(ctx.con):
        m = _mov(ctx, mov_id)
        if m["decisao_duplicidade"] != "pendente":
            raise OperacaoInvalida("não há alerta de duplicidade pendente neste movimento")
        status = "descartado" if decisao == "descartar" else m["status"]
        ctx.con.execute("UPDATE movimentos SET decisao_duplicidade = ?, status = ?, observacao = ? WHERE id = ?",
                        (decisao, status, sanitizar_texto(justificativa), mov_id))
        _atualizar_risco(ctx, mov_id)
        audit.registrar(ctx.con, ctx.nome, "duplicidade_decidida", "movimento", mov_id, decisao=decisao,
                        duplicidade_de=m["duplicidade_de"], justificativa=justificativa)


# ---------------------------------------------------------------- razão e conferência

def carregar_razao(ctx: Contexto, nome: str, bruto: bytes, formato: str = "fortes_importacao",
                   colunas: dict | None = None) -> dict:
    """Substitui o Razão carregado antes (o novo arquivo deve cobrir todo o histórico da conta)."""
    ctx.exigir("cadastrar")
    h = deduplicator.sha256(bruto)
    _bloquear_repetido(ctx, h, nome)
    if formato == "fortes_importacao":
        partidas = fortes_razao_parser.ler_lancamentos_fortes(bruto)
    elif formato == "tabular":
        c = colunas or {}
        partidas = fortes_razao_parser.ler_razao_tabular(bruto, nome, c["data"], c["conta"], c["debito"],
                                                         c["credito"], c.get("historico"))
    else:
        raise OperacaoInvalida(f"formato de razão desconhecido: {formato}")
    with transacao(ctx.con):
        ctx.con.execute("DELETE FROM razao")
        ctx.con.execute("UPDATE arquivos SET status = 'substituido' WHERE tipo = 'razao' AND status = 'carregado'")
        arq = _guardar_original(ctx, nome, bruto, "razao", h)
        ctx.con.executemany(
            "INSERT INTO razao (arquivo_id, data, conta, debito_centavos, credito_centavos, historico) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(arq, p["data"], p["conta"], p["debito_centavos"], p["credito_centavos"], p["historico"]) for p in partidas],
        )
        definir_parametro(ctx.con, "formato_razao", formato)
        audit.registrar(ctx.con, ctx.nome, "razao_carregado", "arquivo", arq, nome=nome, partidas=len(partidas),
                        formato=formato)
    return {"partidas": len(partidas)}


def limites_periodo(periodo: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periodo or ""):
        raise OperacaoInvalida("período no formato AAAA-MM")
    a, m = map(int, periodo.split("-"))
    return f"{periodo}-01", f"{periodo}-{calendar.monthrange(a, m)[1]:02d}"


def informar_saldos(ctx: Contexto, periodo: str, conta_banco: str, inicial: int, final: int) -> None:
    ctx.exigir("conciliar")
    limites_periodo(periodo)
    with transacao(ctx.con):
        ctx.con.execute(
            "INSERT INTO saldos_extrato (periodo, conta_banco, saldo_inicial_centavos, saldo_final_centavos, "
            "informado_por, informado_em) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(periodo, conta_banco) DO UPDATE SET "
            "saldo_inicial_centavos = excluded.saldo_inicial_centavos, saldo_final_centavos = excluded.saldo_final_centavos, "
            "informado_por = excluded.informado_por, informado_em = excluded.informado_em",
            (periodo, conta_banco, inicial, final, ctx.nome, agora()),
        )
        audit.registrar(ctx.con, ctx.nome, "saldos_extrato_informados", "conciliacao", f"{periodo}/{conta_banco}",
                        inicial=inicial, final=final)


MARCA_RE = re.compile(r"\[[A-Z0-9]{2,6}-\d{6}-\d{6}\]")


def conferir(ctx: Contexto, periodo: str, conta_banco: str) -> reconciler.Conferencia:
    ctx.exigir("conciliar")
    ini, fim = limites_periodo(periodo)
    s = ctx.con.execute("SELECT * FROM saldos_extrato WHERE periodo = ? AND conta_banco = ?",
                        (periodo, conta_banco)).fetchone()
    if s is None:
        raise OperacaoInvalida("informe o saldo inicial e o final do extrato do período")
    valores = [r[0] for r in ctx.con.execute(
        "SELECT valor_centavos FROM movimentos WHERE conta_banco = ? AND data BETWEEN ? AND ? AND status <> 'descartado'",
        (conta_banco, ini, fim))]
    classif = ctx.con.execute(
        "SELECT * FROM plano_contas WHERE vigente = 1 AND reduzido = ?", (conta_banco,)).fetchone()
    nomes_conta = [conta_banco] + ([classif["classificacao"]] if classif else [])
    marks = ",".join("?" * len(nomes_conta))
    saldo_razao = ctx.con.execute(
        f"SELECT COALESCE(SUM(debito_centavos - credito_centavos), 0) FROM razao WHERE conta IN ({marks}) AND data <= ?",
        (*nomes_conta, fim)).fetchone()[0]
    no_razao = set()
    for (h,) in ctx.con.execute("SELECT historico FROM razao WHERE historico IS NOT NULL"):
        no_razao.update(MARCA_RE.findall(h))
    pendentes = 0
    for m in ctx.con.execute(
            "SELECT id, data, valor_centavos, marca FROM movimentos WHERE conta_banco = ? AND data <= ? "
            "AND status IN ('classificado', 'exportado')", (conta_banco, fim)):
        if (m["marca"] or fortes_exporter.marca(ctx.prefixo, m["data"], m["id"])) not in no_razao:
            pendentes += m["valor_centavos"]
    for m in ctx.con.execute(
            "SELECT id, tipo, data, valor_centavos, conta_debito, marca FROM lancamentos WHERE data <= ? "
            "AND status IN ('confirmado', 'exportado') AND (conta_debito = ? OR conta_credito = ?)",
            (fim, conta_banco, conta_banco)):
        mk = m["marca"] or fortes_exporter.marca_lancamento(m["tipo"], m["data"], m["id"])
        if mk not in no_razao:
            pendentes += m["valor_centavos"] if m["conta_debito"] == conta_banco else -m["valor_centavos"]
    sem = ctx.con.execute(
        "SELECT COUNT(*) FROM movimentos WHERE conta_banco = ? AND data BETWEEN ? AND ? "
        "AND status IN ('pendente', 'proposto', 'em_espera')", (conta_banco, ini, fim)).fetchone()[0]
    c = reconciler.conferir(periodo, conta_banco, s["saldo_inicial_centavos"], s["saldo_final_centavos"],
                            valores, saldo_razao, pendentes, sem)
    from domain import homologacao
    formato = parametro(ctx.con, "formato_razao")
    razao_ok = 1 if homologacao.razao_homologado(ctx.central, formato) else 0
    with transacao(ctx.con):
        ant = ctx.con.execute("SELECT * FROM conciliacoes WHERE periodo = ? AND conta_banco = ?",
                              (periodo, conta_banco)).fetchone()
        mantem = ant is not None and ant["diferenca_centavos"] == c.diferenca_centavos and ant["justificativa"]
        if c.fecha and sem == 0:
            status = "concluida"
        elif mantem and ant["segunda_revisao_por"]:
            status = "justificada"
        else:
            status = "divergente" if c.diferenca_centavos or c.diferenca_interna_extrato else "aberta"
        ctx.con.execute(
            "INSERT INTO conciliacoes (periodo, conta_banco, saldo_inicial_extrato, movimentacao_extrato, "
            "saldo_final_extrato, saldo_final_contabil, diferenca_centavos, justificativa, justificado_por, "
            "segunda_revisao_por, status, atualizado_em, razao_homologado, formato_razao) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(periodo, conta_banco) DO UPDATE SET saldo_inicial_extrato = excluded.saldo_inicial_extrato, "
            "movimentacao_extrato = excluded.movimentacao_extrato, saldo_final_extrato = excluded.saldo_final_extrato, "
            "saldo_final_contabil = excluded.saldo_final_contabil, diferenca_centavos = excluded.diferenca_centavos, "
            "justificativa = excluded.justificativa, justificado_por = excluded.justificado_por, "
            "segunda_revisao_por = excluded.segunda_revisao_por, status = excluded.status, "
            "atualizado_em = excluded.atualizado_em, razao_homologado = excluded.razao_homologado, "
            "formato_razao = excluded.formato_razao",
            (periodo, conta_banco, c.saldo_inicial_extrato, c.movimentacao_extrato, c.saldo_final_extrato,
             c.saldo_final_contabil, c.diferenca_centavos,
             ant["justificativa"] if mantem else None, ant["justificado_por"] if mantem else None,
             ant["segunda_revisao_por"] if mantem else None, status, agora(), razao_ok, formato),
        )
        audit.registrar(ctx.con, ctx.nome, "conferencia_saldo", "conciliacao", f"{periodo}/{conta_banco}",
                        diferenca=c.diferenca_centavos, interna=c.diferenca_interna_extrato, status=status,
                        razao_homologado=bool(razao_ok), formato_razao=formato)
    return c


def conciliacao(con, periodo: str, conta_banco: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM conciliacoes WHERE periodo = ? AND conta_banco = ?",
                       (periodo, conta_banco)).fetchone()


def justificar_diferenca(ctx: Contexto, periodo: str, conta_banco: str, texto: str) -> None:
    ctx.exigir("conciliar")
    if len(texto.strip()) < 10:
        raise OperacaoInvalida("descreva a explicação da diferença (mínimo 10 caracteres)")
    with transacao(ctx.con):
        c = conciliacao(ctx.con, periodo, conta_banco)
        if c is None or c["diferenca_centavos"] == 0:
            raise OperacaoInvalida("não há diferença a justificar; rode a conferência")
        ctx.con.execute(
            "UPDATE conciliacoes SET justificativa = ?, justificado_por = ?, segunda_revisao_por = NULL, "
            "status = 'divergente', atualizado_em = ? WHERE id = ?",
            (sanitizar_texto(texto), ctx.nome, agora(), c["id"]))
        audit.registrar(ctx.con, ctx.nome, "diferenca_justificada", "conciliacao", c["id"],
                        diferenca=c["diferenca_centavos"], texto=texto)


def revisar_diferenca(ctx: Contexto, periodo: str, conta_banco: str) -> None:
    ctx.exigir("revisar_diferenca")
    with transacao(ctx.con):
        c = conciliacao(ctx.con, periodo, conta_banco)
        if c is None or not c["justificativa"]:
            raise OperacaoInvalida("não há justificativa registrada")
        if c["justificado_por"] == ctx.nome:
            raise OperacaoInvalida("quem justificou a diferença não pode fazer a segunda revisão")
        ctx.con.execute("UPDATE conciliacoes SET segunda_revisao_por = ?, status = 'justificada', atualizado_em = ? "
                        "WHERE id = ?", (ctx.nome, agora(), c["id"]))
        audit.registrar(ctx.con, ctx.nome, "diferenca_revisada", "conciliacao", c["id"])


# ---------------------------------------------------------------- exportação

def lancamentos_para_lote(con, periodo: str) -> list[dict]:
    """Lançamentos manuais confirmados do período, no mesmo formato dos movimentos, para o exportador."""
    ini, fim = limites_periodo(periodo)
    itens = []
    for r in con.execute("SELECT * FROM lancamentos WHERE status = 'confirmado' AND lote_id IS NULL "
                         "AND data BETWEEN ? AND ? ORDER BY data, id", (ini, fim)):
        itens.append({
            "id": r["id"], "_origem": "lancamento", "_rotulo": f"lançamento manual {r['id']}",
            "_marca": fortes_exporter.marca_lancamento(r["tipo"], r["data"], r["id"]),
            "data": r["data"], "valor_centavos": r["valor_centavos"], "historico": r["historico"],
            "historico_contabil": r["historico"], "conta_debito": r["conta_debito"], "conta_credito": r["conta_credito"],
            "exige_segunda_confirmacao": 1, "revisado_por": r["criado_por"],
            "segunda_confirmacao_por": r["confirmado_por"], "decisao_duplicidade": "nao_aplica",
            "ref_externa": r["ref_externa"],
        })
    return itens


def movimentos_para_lote(con, periodo: str, conta_banco: str) -> list[dict]:
    ini, fim = limites_periodo(periodo)
    return [dict(r) for r in con.execute(
        "SELECT * FROM movimentos WHERE conta_banco = ? AND data BETWEEN ? AND ? AND status = 'classificado' "
        "AND lote_id IS NULL ORDER BY data, id", (conta_banco, ini, fim))]


def marcas_no_razao(con) -> dict[str, int]:
    """marca -> quantas partidas do Razão a contêm."""
    cont: dict[str, int] = {}
    for (h,) in con.execute("SELECT historico FROM razao WHERE historico IS NOT NULL"):
        for mk in set(MARCA_RE.findall(h)):
            cont[mk] = cont.get(mk, 0) + 1
    return cont


def checar_duplicidade_exportacao(ctx: Contexto, movs: list[dict]) -> list[str]:
    """Impede exportar de novo o que já está no Fortes ou num lote aceito."""
    problemas = []
    no_razao = marcas_no_razao(ctx.con)
    for m in movs:
        mk = fortes_exporter.marca(ctx.prefixo, m["data"], m["id"])
        if mk in no_razao:
            problemas.append(f"movimento {m['id']}: a marca {mk} já está no Razão do Fortes; exportar de novo duplicaria")
        anterior = ctx.con.execute(
            "SELECT l.id FROM lote_itens i JOIN lotes l ON l.id = i.lote_id "
            "WHERE i.movimento_id = ? AND l.status = 'aceito'", (m["id"],)).fetchone()
        if anterior:
            problemas.append(f"movimento {m['id']}: já foi importado no lote aceito {anterior['id']}")
        igual = ctx.con.execute(
            "SELECT i.lote_id, i.movimento_id FROM lote_itens i JOIN lotes l ON l.id = i.lote_id "
            "JOIN movimentos o ON o.id = i.movimento_id WHERE l.status IN ('aceito', 'gerado') AND o.id <> ? "
            "AND o.data = ? AND o.valor_centavos = ? AND o.conta_debito = ? AND o.conta_credito = ? "
            "AND o.historico = ?",
            (m["id"], m["data"], m["valor_centavos"], m["conta_debito"], m["conta_credito"], m["historico"])).fetchone()
        if igual and m["decisao_duplicidade"] != "manter":
            problemas.append(f"movimento {m['id']}: igual ao movimento {igual['movimento_id']} do lote "
                             f"{igual['lote_id']} (data, valor, contas e histórico). Se não for duplicado, "
                             "registre a decisão na aba Duplicidades")
    return problemas


def checar_duplicidade_lancamentos(ctx: Contexto, lancs: list[dict]) -> list[str]:
    problemas = []
    no_razao = marcas_no_razao(ctx.con)
    textos = [h for (h,) in ctx.con.execute("SELECT historico FROM razao WHERE historico IS NOT NULL")]
    for m in lancs:
        if m["_marca"] in no_razao:
            problemas.append(f"{m['_rotulo']}: a marca {m['_marca']} já está no Razão do Fortes")
        ref = m.get("ref_externa")
        if ref and any(ref in t for t in textos):
            problemas.append(f"{m['_rotulo']}: a referência {ref} já aparece no Razão do Fortes; exportar duplicaria")
        igual = ctx.con.execute(
            "SELECT id FROM lancamentos WHERE id <> ? AND status = 'exportado' AND data = ? AND valor_centavos = ? "
            "AND conta_debito = ? AND conta_credito = ? AND historico = ?",
            (m["id"], m["data"], m["valor_centavos"], m["conta_debito"], m["conta_credito"], m["historico"])).fetchone()
        if igual:
            problemas.append(f"{m['_rotulo']}: igual ao lançamento {igual['id']} já exportado")
    return problemas


def pre_validar_lote(ctx: Contexto, periodo: str, conta_banco: str) -> tuple[list[dict], list[str]]:
    ini, fim = limites_periodo(periodo)
    movs = movimentos_para_lote(ctx.con, periodo, conta_banco) + lancamentos_para_lote(ctx.con, periodo)
    c = conciliacao(ctx.con, periodo, conta_banco)
    problemas = fortes_exporter.validar(movs, plano_vigente(ctx.con), dict(c) if c else None)
    soltos = ctx.con.execute(
        "SELECT COUNT(*) FROM movimentos WHERE conta_banco = ? AND data BETWEEN ? AND ? AND status IN ('pendente', 'proposto')",
        (conta_banco, ini, fim)).fetchone()[0]
    if soltos:
        problemas.append(f"{soltos} movimento(s) do período sem revisão: classifique ou coloque em espera")
    dup = ctx.con.execute(
        "SELECT COUNT(*) FROM movimentos WHERE conta_banco = ? AND data BETWEEN ? AND ? AND decisao_duplicidade = 'pendente'",
        (conta_banco, ini, fim)).fetchone()[0]
    if dup:
        problemas.append(f"{dup} alerta(s) de duplicidade do período sem decisão")
    problemas += checar_duplicidade_exportacao(ctx, [m for m in movs if m.get("_origem") != "lancamento"])
    problemas += checar_duplicidade_lancamentos(ctx, [m for m in movs if m.get("_origem") == "lancamento"])
    aberto = ctx.con.execute("SELECT * FROM travas_periodo WHERE periodo = ? AND conta_banco = ?",
                             (periodo, conta_banco)).fetchone()
    if aberto:
        problemas.append(f"há um lote deste período aguardando retorno do Fortes (gerado por {aberto['usuario']}); "
                         "registre o retorno antes de gerar outro")
    return movs, list(dict.fromkeys(problemas))


def gerar_lote(ctx: Contexto, periodo: str, conta_banco: str) -> dict:
    ctx.exigir("exportar")
    try:
        return _gerar_lote(ctx, periodo, conta_banco)
    except LoteBloqueado as exc:
        # o rollback desfaz tudo; a tentativa bloqueada é registrada à parte
        with transacao(ctx.con):
            audit.registrar(ctx.con, ctx.nome, "lote_bloqueado", "lote", None, periodo=periodo,
                            conta_banco=conta_banco, problemas=exc.problemas)
        raise


def _gerar_lote(ctx: Contexto, periodo: str, conta_banco: str) -> dict:
    with transacao(ctx.con):
        movs, problemas = pre_validar_lote(ctx, periodo, conta_banco)
        if problemas:
            raise LoteBloqueado(problemas)
        limite = limite_historico(ctx.con)
        geradas = fortes_exporter.gerar_linhas(movs, plano_vigente(ctx.con), ctx.prefixo, limite)
        conteudo = fortes_exporter.conteudo_arquivo(geradas)
        ida_volta = fortes_exporter.conferir_ida_e_volta(conteudo, movs, geradas)
        if ida_volta:
            raise LoteBloqueado(["conferência de ida e volta do arquivo falhou: " + p for p in ida_volta])
        uid = uuid.uuid4().hex
        destino = ctx.pasta / "arquivos" / "exportacoes" / f"fortes_{periodo}_{conta_banco}_{uid[:8]}.csv"
        ctx.gravar_arquivo(destino, conteudo)
        try:
            total = sum(abs(m["valor_centavos"]) for m in movs)
            truncados = sum(g.truncado for g in geradas)
            sha = deduplicator.sha256(conteudo)
            cur = ctx.con.execute(
                "INSERT INTO lotes (uuid, periodo, conta_banco, caminho, sha256, quantidade, total_centavos, gerado_por, "
                "gerado_em, limite_historico, truncados) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, periodo, conta_banco, str(destino.relative_to(ctx.pasta)), sha,
                 len(movs), total, ctx.nome, agora(), limite, truncados))
            lote_id = cur.lastrowid
            for g in geradas:
                if g.origem == "lancamento":
                    ctx.con.execute(
                        "INSERT INTO lote_itens_lanc (lote_id, lancamento_id, marca, linha_exportada, historico_completo, "
                        "historico_exportado, truncado) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (lote_id, g.movimento_id, g.marca, g.linha, g.historico_completo, g.historico_exportado,
                         int(g.truncado)))
                    ctx.con.execute("UPDATE lancamentos SET status = 'exportado', lote_id = ?, marca = ? WHERE id = ?",
                                    (lote_id, g.marca, g.movimento_id))
                    continue
                ctx.con.execute(
                    "INSERT INTO lote_itens (lote_id, movimento_id, marca, linha_exportada, historico_completo, "
                    "historico_exportado, truncado) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (lote_id, g.movimento_id, g.marca, g.linha, g.historico_completo, g.historico_exportado,
                     int(g.truncado)))
                ctx.con.execute("UPDATE movimentos SET status = 'exportado', lote_id = ?, marca = ? WHERE id = ?",
                                (lote_id, g.marca, g.movimento_id))
            ctx.con.execute("INSERT INTO travas_periodo (periodo, conta_banco, usuario, desde) VALUES (?, ?, ?, ?)",
                            (periodo, conta_banco, ctx.nome, agora()))
            audit.registrar(ctx.con, ctx.nome, "lote_gerado", "lote", lote_id, periodo=periodo, quantidade=len(movs),
                            total=total, sha256=sha, limite_historico=limite, truncados=truncados)
        except BaseException:
            destino.chmod(0o644)
            destino.unlink(missing_ok=True)
            raise
    return {"lote_id": lote_id, "arquivo": destino, "quantidade": len(movs), "total_centavos": total,
            "truncados": truncados, "limite_historico": limite}


def arquivo_lote(ctx: Contexto, lote_id: int) -> bytes:
    """Conteúdo do lote só se o SHA-256 bater com o gravado na geração."""
    ctx.exigir("ver_equipe")
    l = ctx.con.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if l is None:
        raise OperacaoInvalida("lote inexistente")
    caminho = ctx.pasta / l["caminho"]
    if not caminho.exists():
        raise OperacaoInvalida(f"arquivo do lote {lote_id} sumiu; restaure do backup")
    bruto = ctx.ler_arquivo(caminho)
    if deduplicator.sha256(bruto) != l["sha256"]:
        with transacao(ctx.con):
            audit.registrar(ctx.con, ctx.nome, "lote_adulterado", "lote", lote_id)
        raise OperacaoInvalida(f"arquivo do lote {lote_id} foi alterado depois de gerado (SHA-256 diferente); "
                               "não importe este arquivo")
    return bruto


def _ler_ou_vazio(ctx: Contexto, f: Path) -> bytes:
    try:
        return ctx.ler_arquivo(f)
    except cripto.ErroCripto:
        return b"\x00ilegivel"


def verificar_integridade(ctx: Contexto) -> list[str]:
    """Confere originais e lotes contra o SHA-256 gravado e o banco contra o integrity_check."""
    ctx.exigir("ver_equipe")
    problemas = []
    r = ctx.con.execute("PRAGMA integrity_check").fetchone()[0]
    if r != "ok":
        problemas.append(f"banco da empresa: integrity_check = {r}")
    for a in ctx.con.execute("SELECT id, nome_original, caminho, sha256 FROM arquivos"):
        f = ctx.pasta / a["caminho"]
        if not f.exists():
            problemas.append(f"arquivo original {a['id']} ({a['nome_original']}) ausente")
        elif deduplicator.sha256(_ler_ou_vazio(ctx, f)) != a["sha256"]:
            problemas.append(f"arquivo original {a['id']} ({a['nome_original']}) alterado ou ilegível")
    for l in ctx.con.execute("SELECT id, caminho, sha256, quantidade FROM lotes"):
        f = ctx.pasta / l["caminho"]
        if not f.exists():
            problemas.append(f"lote {l['id']}: arquivo ausente")
        elif deduplicator.sha256(_ler_ou_vazio(ctx, f)) != l["sha256"]:
            problemas.append(f"lote {l['id']}: arquivo alterado depois de gerado")
        n = ctx.con.execute("SELECT COUNT(*) FROM lote_itens WHERE lote_id = ?", (l["id"],)).fetchone()[0]
        if n and n != l["quantidade"]:
            problemas.append(f"lote {l['id']}: {n} itens registrados para {l['quantidade']} lançamentos")
    for d in ctx.con.execute("SELECT id, nome_original, caminho, sha256 FROM documentos"):
        f = ctx.pasta / d["caminho"]
        if not f.exists():
            problemas.append(f"documento {d['id']} ({d['nome_original']}) ausente")
        elif deduplicator.sha256(_ler_ou_vazio(ctx, f)) != d["sha256"]:
            problemas.append(f"documento {d['id']} ({d['nome_original']}) alterado ou ilegível")
    problemas += audit.verificar_cadeia(ctx.con, "audit_log")
    with transacao(ctx.con):
        audit.registrar(ctx.con, ctx.nome, "verificacao_integridade", "empresa", ctx.empresa["slug"],
                        problemas=len(problemas), hash_auditoria=audit.hash_final(ctx.con))
    return problemas


def conferir_lote_no_razao(ctx: Contexto, lote_id: int) -> dict:
    """Depois da importação real: cada lançamento do lote está no Razão do Fortes, uma vez só,
    com a mesma data, valor e lado na conta do banco? (e nas contrapartidas, se o Razão as trouxer)."""
    ctx.exigir("conciliar")
    l = ctx.con.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if l is None:
        raise OperacaoInvalida("lote inexistente")
    if l["status"] != "aceito":
        raise OperacaoInvalida("registre o retorno 'importado sem erro' antes de conferir no Razão")
    carga_razao = ctx.con.execute("SELECT MAX(a.enviado_em) FROM arquivos a WHERE a.tipo = 'razao' "
                                  "AND a.status = 'carregado'").fetchone()[0]
    if not carga_razao or carga_razao < l["retorno_em"]:
        raise OperacaoInvalida("carregue um Razão exportado do Fortes depois da importação deste lote")
    itens = ctx.con.execute(
        "SELECT i.*, m.data, m.valor_centavos, m.conta_debito, m.conta_credito, m.conta_banco "
        "FROM lote_itens i JOIN movimentos m ON m.id = i.movimento_id WHERE i.lote_id = ?", (lote_id,)).fetchall()
    ausentes, divergentes, duplicados, encontrados = [], [], [], 0
    for it in ctx.con.execute(
            "SELECT i.marca, i.historico_exportado, m.data, m.valor_centavos, m.conta_debito, m.conta_credito "
            "FROM lote_itens_lanc i JOIN lancamentos m ON m.id = i.lancamento_id WHERE i.lote_id = ?", (lote_id,)):
        partidas = ctx.con.execute("SELECT * FROM razao WHERE historico LIKE ?", (f"%{it['marca']}%",)).fetchall()
        deb = [p for p in partidas if p["conta"] == it["conta_debito"] and p["debito_centavos"] == it["valor_centavos"]
               and p["data"] == it["data"]]
        cre = [p for p in partidas if p["conta"] == it["conta_credito"] and p["credito_centavos"] == it["valor_centavos"]
               and p["data"] == it["data"]]
        if not partidas:
            ausentes.append(it["marca"])
        elif len(deb) > 1 or len(cre) > 1:
            duplicados.append(f"{it['marca']} aparece mais de uma vez no Razão")
        elif not deb or not cre:
            divergentes.append(f"{it['marca']}: data, valor ou contas no Razão diferem do lançamento manual")
        else:
            encontrados += 1
    for it in itens:
        partidas = ctx.con.execute("SELECT * FROM razao WHERE historico LIKE ?",
                                   (f"%{it['marca']}%",)).fetchall()
        banco = [p for p in partidas if p["conta"] == it["conta_banco"]]
        if not banco:
            ausentes.append(it["marca"])
            continue
        if len(banco) > 1:
            duplicados.append(f"{it['marca']} aparece {len(banco)} vezes na conta do banco")
        p = banco[0]
        valor = abs(it["valor_centavos"])
        lado_ok = (p["debito_centavos"] == valor) if it["conta_debito"] == it["conta_banco"] else (
            p["credito_centavos"] == valor)
        if p["data"] != it["data"] or not lado_ok:
            divergentes.append(f"{it['marca']}: Razão {p['data']} D {p['debito_centavos']} C {p['credito_centavos']}; "
                               f"esperado {it['data']} {valor} no lado {'D' if it['conta_debito'] == it['conta_banco'] else 'C'}")
        contra = it["conta_credito"] if it["conta_debito"] == it["conta_banco"] else it["conta_debito"]
        outras = [q for q in partidas if q["conta"] != it["conta_banco"]]
        if outras and not any(q["conta"] == contra for q in outras):
            divergentes.append(f"{it['marca']}: contrapartida no Razão é {outras[0]['conta']}, esperado {contra}")
        if not (it["historico_exportado"].split(" [")[0][:20] in (p["historico"] or "")):
            divergentes.append(f"{it['marca']}: histórico no Razão não corresponde ao exportado")
        encontrados += 1
    resultado = {
        "lote_id": lote_id, "itens": l["quantidade"], "encontrados": encontrados, "ausentes": ausentes,
        "divergentes": divergentes, "duplicados": duplicados,
        "aprovado": bool(l["quantidade"]) and not ausentes and not divergentes and not duplicados,
        "formato_razao": parametro(ctx.con, "formato_razao"),
    }
    with transacao(ctx.con):
        ctx.con.execute("UPDATE lotes SET conferencia_razao = ?, conferido_por = ?, conferido_em = ? WHERE id = ?",
                        (json.dumps(resultado, ensure_ascii=False), ctx.nome, agora(), lote_id))
        audit.registrar(ctx.con, ctx.nome, "lote_conferido_no_razao", "lote", lote_id,
                        aprovado=resultado["aprovado"], ausentes=len(ausentes), divergentes=len(divergentes),
                        duplicados=len(duplicados))
    return resultado


def itens_lote(con, lote_id: int) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM lote_itens WHERE lote_id = ? ORDER BY movimento_id", (lote_id,)).fetchall()


def registrar_retorno(ctx: Contexto, lote_id: int, aceito: bool, observacao: str) -> None:
    ctx.exigir("registrar_retorno")
    if not aceito and not observacao.strip():
        raise OperacaoInvalida("informe a mensagem de erro do Fortes")
    with transacao(ctx.con):
        l = ctx.con.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
        if l is None or l["status"] != "gerado":
            raise OperacaoInvalida("lote inexistente ou com retorno já registrado")
        ctx.con.execute("UPDATE lotes SET status = ?, retorno_por = ?, retorno_em = ?, retorno_obs = ? WHERE id = ?",
                        ("aceito" if aceito else "rejeitado", ctx.nome, agora(), sanitizar_texto(observacao), lote_id))
        if not aceito:
            ctx.con.execute("UPDATE movimentos SET status = 'classificado', lote_id = NULL, marca = NULL "
                            "WHERE lote_id = ?", (lote_id,))
            ctx.con.execute("UPDATE lancamentos SET status = 'confirmado', lote_id = NULL, marca = NULL "
                            "WHERE lote_id = ?", (lote_id,))
        ctx.con.execute("DELETE FROM travas_periodo WHERE periodo = ? AND conta_banco = ?",
                        (l["periodo"], l["conta_banco"]))
        audit.registrar(ctx.con, ctx.nome, "retorno_fortes", "lote", lote_id, aceito=aceito, observacao=observacao)


def relatorio_pendencias(ctx: Contexto, periodo: str, conta_banco: str) -> Path:
    ctx.exigir("ver_equipe")
    ini, fim = limites_periodo(periodo)
    linhas = ctx.con.execute(
        "SELECT id, data, valor_centavos, historico, status, decisao_duplicidade, motivos_risco, observacao "
        "FROM movimentos WHERE conta_banco = ? AND data BETWEEN ? AND ? AND (status IN ('pendente','proposto','em_espera') "
        "OR decisao_duplicidade = 'pendente' OR (exige_segunda_confirmacao = 1 AND segunda_confirmacao_por IS NULL "
        "AND status = 'classificado')) ORDER BY data, id", (conta_banco, ini, fim)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "data", "valor", "historico", "status", "duplicidade", "segunda_revisao", "observacao"])
    for r in linhas:
        w.writerow([r["id"], r["data"], formatar_br(r["valor_centavos"], simbolo=False),
                    "'" + r["historico"] if r["historico"][:1] in "=+-@" else r["historico"],
                    r["status"], r["decisao_duplicidade"], r["motivos_risco"] or "", r["observacao"] or ""])
    destino = ctx.pasta / "arquivos" / "relatorios" / f"pendencias_{periodo}_{conta_banco}_{uuid.uuid4().hex[:6]}.csv"
    ctx.gravar_arquivo(destino, buf.getvalue().encode("utf-8-sig"))
    audit.registrar(ctx.con, ctx.nome, "relatorio_pendencias", "relatorio", destino.name, itens=len(linhas))
    return destino


def limite_historico(con) -> int:
    import config
    return int(parametro(con, "limite_historico", str(config.LIMITE_HISTORICO)))


def definir_limite_historico(ctx: Contexto, limite: int) -> None:
    """Muda o limite só para lotes futuros; lotes já gerados guardam o limite que usaram."""
    ctx.exigir("cadastrar")
    fortes_exporter.validar_limite(limite)
    anterior = limite_historico(ctx.con)
    with transacao(ctx.con):
        definir_parametro(ctx.con, "limite_historico", str(limite))
        audit.registrar(ctx.con, ctx.nome, "limite_historico_definido", "parametro", "limite_historico",
                        anterior=anterior, novo=limite)


def definir_prefixo(ctx: Contexto, prefixo: str) -> None:
    ctx.exigir("cadastrar")
    fortes_exporter.validar_prefixo(prefixo)
    with transacao(ctx.con):
        definir_parametro(ctx.con, "prefixo_marca", prefixo)
        audit.registrar(ctx.con, ctx.nome, "prefixo_definido", "parametro", "prefixo_marca", valor=prefixo)


def definir_conta_banco_padrao(ctx: Contexto, reduzido: str) -> None:
    ctx.exigir("cadastrar")
    _exigir_conta_valida(ctx.con, reduzido, "conta do banco")
    with transacao(ctx.con):
        definir_parametro(ctx.con, "conta_banco_padrao", str(reduzido))
        audit.registrar(ctx.con, ctx.nome, "conta_banco_definida", "parametro", "conta_banco_padrao", valor=reduzido)
