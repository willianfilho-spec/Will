"""Lançamentos manuais: provisões, reclassificações, transposições e ajustes.

São os lançamentos que não nascem de uma linha do extrato (ex.: D 247 / C 57). Têm a mesma
governança dos demais:
- quem cria não confirma: outra pessoa (revisor ou aprovador) dá a segunda confirmação, sempre;
- só entram no lote depois de confirmados, com as mesmas validações (contas do plano, partidas
  íntegras, duplicidade, conferência de saldo);
- depois de criados não são editados: descarta-se e cria-se outro;
- podem apontar o documento que os comprova (folha, guia, recibo).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

import config
from domain import deduplicator
from domain.money import ValorInvalido, para_centavos
from domain.operacoes import Contexto, OperacaoInvalida, _exigir_conta_valida, plano_vigente
from exporters.fortes_exporter import historico_ascii
from parsers.comum import ErroEstrutural, decodificar, para_data, sanitizar_texto
from storage import audit
from storage.database import agora, transacao

TAG_FINAL = re.compile(r"\s*(\[[A-Z]{2,6}-\d{3,}(?:-\d{3,})?\])\s*$")
TIPO_POR_TAG = {"MUL": "reclassificacao", "JUR": "reclassificacao", "DRF": "reclassificacao", "REC": "reclassificacao",
                "TRP": "transposicao", "PRV": "provisao", "AJU": "ajuste"}


def _separar_tag(historico: str) -> tuple[str, str | None]:
    m = TAG_FINAL.search(historico)
    if not m:
        return historico.strip(), None
    return historico[:m.start()].strip(), m.group(1)


def _igual_existente(con, data: str, deb: str, cred: str, valor: int, hist: str):
    return con.execute(
        "SELECT id, status FROM lancamentos WHERE status <> 'descartado' AND data = ? AND conta_debito = ? "
        "AND conta_credito = ? AND valor_centavos = ? AND historico = ?", (data, deb, cred, valor, hist)).fetchone()


def criar(ctx: Contexto, tipo: str, data: str, conta_debito: str, conta_credito: str, valor_centavos: int,
          historico: str, documento_id: int | None = None, ref_externa: str | None = None,
          observacao: str | None = None, justificar_duplicidade: str | None = None) -> int:
    ctx.exigir("lancamento_manual")
    if tipo not in config.TIPOS_LANCAMENTO:
        raise OperacaoInvalida(f"tipo inválido: {tipo}")
    try:
        d = para_data(data).isoformat()
    except ValueError as exc:
        raise OperacaoInvalida(str(exc)) from exc
    if not isinstance(valor_centavos, int) or isinstance(valor_centavos, bool) or valor_centavos <= 0:
        raise OperacaoInvalida("o valor do lançamento deve ser maior que zero")
    if str(conta_debito) == str(conta_credito):
        raise OperacaoInvalida("débito e crédito não podem ser a mesma conta")
    _exigir_conta_valida(ctx.con, str(conta_debito), "conta de débito")
    _exigir_conta_valida(ctx.con, str(conta_credito), "conta de crédito")
    hist = sanitizar_texto(historico)
    if not historico_ascii(hist):
        raise OperacaoInvalida("informe o histórico do lançamento")
    with transacao(ctx.con):
        if documento_id is not None and ctx.con.execute("SELECT 1 FROM documentos WHERE id = ?", (documento_id,)).fetchone() is None:
            raise OperacaoInvalida("documento de comprovação inexistente nesta empresa")
        igual = _igual_existente(ctx.con, d, str(conta_debito), str(conta_credito), valor_centavos, hist)
        if igual and not (justificar_duplicidade or "").strip():
            raise OperacaoInvalida(f"já existe o lançamento {igual['id']} ({igual['status']}) igual a este (data, contas, "
                                   "valor e histórico). Se não for duplicado, informe a justificativa")
        obs = sanitizar_texto(observacao) or None
        if igual:
            obs = f"Possível duplicidade do #{igual['id']} mantida: {sanitizar_texto(justificar_duplicidade)}. {obs or ''}".strip()
        cur = ctx.con.execute(
            "INSERT INTO lancamentos (tipo, data, conta_debito, conta_credito, valor_centavos, historico, ref_externa, "
            "documento_id, criado_por, criado_em, observacao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tipo, d, str(conta_debito), str(conta_credito), valor_centavos, hist, ref_externa, documento_id,
             ctx.nome, agora(), obs))
        audit.registrar(ctx.con, ctx.nome, "lancamento_criado", "lancamento", cur.lastrowid, tipo=tipo, data=d,
                        debito=conta_debito, credito=conta_credito, valor=valor_centavos,
                        duplicidade_justificada=bool(igual))
    return cur.lastrowid


def confirmar(ctx: Contexto, lanc_id: int) -> None:
    ctx.exigir("segunda_confirmacao")
    with transacao(ctx.con):
        l = ctx.con.execute("SELECT * FROM lancamentos WHERE id = ?", (lanc_id,)).fetchone()
        if l is None or l["status"] != "aguardando_confirmacao":
            raise OperacaoInvalida("lançamento inexistente ou não está aguardando confirmação")
        if l["criado_por"] == ctx.nome:
            audit.registrar(ctx.con, ctx.nome, "confirmacao_lancamento_negada_mesmo_usuario", "lancamento", lanc_id)
            raise OperacaoInvalida("quem criou o lançamento não pode confirmá-lo")
        ctx.con.execute("UPDATE lancamentos SET status = 'confirmado', confirmado_por = ?, confirmado_em = ? WHERE id = ?",
                        (ctx.nome, agora(), lanc_id))
        audit.registrar(ctx.con, ctx.nome, "lancamento_confirmado", "lancamento", lanc_id, criado_por=l["criado_por"])


def descartar(ctx: Contexto, lanc_id: int, motivo: str) -> None:
    ctx.exigir("lancamento_manual")
    if len(motivo.strip()) < 5:
        raise OperacaoInvalida("informe o motivo do descarte")
    with transacao(ctx.con):
        l = ctx.con.execute("SELECT * FROM lancamentos WHERE id = ?", (lanc_id,)).fetchone()
        if l is None or l["status"] not in ("aguardando_confirmacao", "confirmado"):
            raise OperacaoInvalida("só lançamento ainda não exportado pode ser descartado")
        ctx.con.execute("UPDATE lancamentos SET status = 'descartado', observacao = ? WHERE id = ?",
                        (f"Descartado por {ctx.nome}: {sanitizar_texto(motivo)}", lanc_id))
        audit.registrar(ctx.con, ctx.nome, "lancamento_descartado", "lancamento", lanc_id, motivo=motivo)


def listar(con, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return con.execute("SELECT * FROM lancamentos WHERE status = ? ORDER BY data, id", (status,)).fetchall()
    return con.execute("SELECT * FROM lancamentos ORDER BY data DESC, id DESC").fetchall()


def importar_leiaute_fortes(ctx: Contexto, nome: str, bruto: bytes, tipo: str | None = None,
                            documento_id: int | None = None) -> dict:
    """Importa lançamentos já prontos no leiaute do Fortes (data;débito;crédito;valor;histórico;;;;).
    Tudo ou nada: uma linha com problema recusa o arquivo. Cada lançamento ainda precisa da confirmação
    de outra pessoa. A marca final do histórico (ex.: [MUL-00311]) vira referência externa."""
    ctx.exigir("lancamento_manual")
    plano = plano_vigente(ctx.con)
    if not plano:
        raise OperacaoInvalida("importe o plano de contas antes")
    sha = deduplicator.sha256(bruto)
    ja = ctx.con.execute("SELECT id, enviado_em FROM documentos WHERE sha256 = ? AND categoria = 'lancamentos' "
                         "AND status = 'processado'", (sha,)).fetchone()
    if ja:
        raise ErroEstrutural([f"arquivo idêntico já importado em {ja['enviado_em']} (documento {ja['id']})"])
    import csv
    import io
    problemas, itens, vistos = [], [], set()
    for n, c in enumerate(csv.reader(io.StringIO(decodificar(bruto), newline=""), delimiter=";"), start=1):
        if not c or not "".join(c).strip():
            continue
        if len(c) < 5:
            problemas.append(f"linha {n}: esperados 9 campos (data;debito;credito;valor;historico;;;;)")
            continue
        try:
            d = para_data(c[0]).isoformat()
            v = para_centavos(c[3])
            if v <= 0:
                raise ValorInvalido("valor deve ser positivo")
        except (ValueError, ValorInvalido) as exc:
            problemas.append(f"linha {n}: {exc}")
            continue
        deb, cred = c[1].strip(), c[2].strip()
        for papel, red in (("débito", deb), ("crédito", cred)):
            conta = plano.get(red)
            if conta is None:
                problemas.append(f"linha {n}: conta de {papel} {red!r} não existe no plano vigente")
            elif not conta.aceita_lancamento:
                problemas.append(f"linha {n}: conta de {papel} {red} é sintética")
        if deb == cred:
            problemas.append(f"linha {n}: débito igual a crédito")
        hist, tag = _separar_tag(sanitizar_texto(c[4]))
        if not hist:
            problemas.append(f"linha {n}: histórico vazio")
        chave = (d, deb, cred, v, hist, tag)
        if chave in vistos:
            problemas.append(f"linha {n}: linha repetida no arquivo")
        vistos.add(chave)
        itens.append((n, d, deb, cred, v, hist, tag))
    if problemas:
        raise ErroEstrutural(problemas)
    if not itens:
        raise ErroEstrutural(["nenhum lançamento encontrado"])
    for n, d, deb, cred, v, hist, tag in itens:
        if _igual_existente(ctx.con, d, deb, cred, v, hist):
            problemas.append(f"linha {n}: já existe lançamento igual (data, contas, valor e histórico)")
    if problemas:
        raise ErroEstrutural(problemas)
    criados = []
    with transacao(ctx.con):
        if documento_id is None:  # guarda o arquivo original (cifrado, só leitura) como comprovação
            import uuid
            uid = uuid.uuid4().hex
            destino = ctx.pasta / "arquivos" / "originais" / f"doc_{uid}.csv"
            ctx.gravar_arquivo(destino, bruto)
            documento_id = ctx.con.execute(
                "INSERT INTO documentos (uuid, nome_original, categoria, descricao, sha256, tamanho, caminho, origem, "
                "enviado_por, usuario_id, enviado_em, status) VALUES (?, ?, 'lancamentos', ?, ?, ?, ?, 'equipe', ?, ?, ?, "
                "'processado')",
                (uid, sanitizar_texto(nome)[:200], "lançamentos importados no leiaute do Fortes", sha, len(bruto),
                 str(destino.relative_to(ctx.pasta)), ctx.nome, ctx.usuario["id"], agora())).lastrowid
        for n, d, deb, cred, v, hist, tag in itens:
            t = tipo or TIPO_POR_TAG.get((tag or "")[1:4], "ajuste")
            cur = ctx.con.execute(
                "INSERT INTO lancamentos (tipo, data, conta_debito, conta_credito, valor_centavos, historico, ref_externa, "
                "documento_id, criado_por, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (t, d, deb, cred, v, hist, tag, documento_id, ctx.nome, agora()))
            criados.append(cur.lastrowid)
        audit.registrar(ctx.con, ctx.nome, "lancamentos_importados", "lancamento", None, arquivo=nome, sha256=sha,
                        quantidade=len(criados), documento_id=documento_id)
    return {"criados": len(criados), "ids": criados, "sha256": sha, "documento_id": documento_id}
