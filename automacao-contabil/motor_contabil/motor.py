"""Orquestração: importar extrato, classificar, validar, revisar e exportar."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from .banco import BancoDeDados, agora
from .classificador_ia import Classificador, SemIA
from .exportador import ExportadorCSVGenerico
from .idempotencia import calcular_chaves, conteudo
from .leitores import ler_extrato
from .modelo import Classificacao, Lancamento, Status, Transacao
from .plano_contas import PlanoDeContas
from .regras import ConjuntoDeRegras
from .texto import formatar_valor

MOTIVO_DUP_ARQUIVO = "possível duplicidade: operação idêntica no mesmo arquivo"
MOTIVO_DUP_BANCO = "possível duplicidade: operação idêntica já importada com outro identificador"


@dataclass
class ResultadoImportacao:
    lote_id: int | None
    lidas: int = 0
    novas: int = 0
    ja_importadas: int = 0
    por_status: Counter = field(default_factory=Counter)
    total_entradas: Decimal = Decimal("0")
    total_saidas: Decimal = Decimal("0")
    arquivo_ja_visto_no_lote: int | None = None

    def resumo(self) -> str:
        linhas = [
            f"Transações lidas: {self.lidas}",
            f"  novas: {self.novas}",
            f"  já importadas antes (ignoradas): {self.ja_importadas}",
            f"Entradas no arquivo: R$ {formatar_valor(self.total_entradas)}",
            f"Saídas no arquivo:   R$ {formatar_valor(self.total_saidas)}",
        ]
        for status in (Status.LIBERADO, Status.PENDENTE, Status.BLOQUEADO):
            linhas.append(f"{status.value.capitalize()}: {self.por_status.get(status, 0)}")
        if self.arquivo_ja_visto_no_lote:
            linhas.append(
                f"Aviso: arquivo idêntico já importado no lote {self.arquivo_ja_visto_no_lote}."
            )
        return "\n".join(linhas)


def montar_lancamento(
    chave: str,
    t: Transacao,
    c: Classificacao,
    plano: PlanoDeContas,
    conta_banco: str,
    alertas: list[str] | None = None,
) -> Lancamento:
    """Regras determinísticas de validação. A IA não participa desta etapa."""
    bloqueios: list[str] = []
    pendencias: list[str] = list(alertas or [])

    if t.valor == 0:
        bloqueios.append("valor zero")

    if problema := plano.problema(conta_banco):
        bloqueios.append(f"conta do banco: {problema}")

    debito = credito = None
    if c.conta_contrapartida is None:
        pendencias.append(c.observacao or "sem classificação")
    else:
        if problema := plano.problema(c.conta_contrapartida):
            bloqueios.append(f"contrapartida: {problema}")
        if t.sentido == "saida":
            debito, credito = c.conta_contrapartida, conta_banco
        else:
            debito, credito = conta_banco, c.conta_contrapartida
        if debito == credito:
            bloqueios.append("conta de débito igual à de crédito")

    if c.fonte == "ia":
        pendencias.append(f"sugestão da IA, requer aprovação ({c.observacao})")

    pendencias.extend(t.alertas)

    historico = t.historico
    if t.favorecido:
        historico = f"{historico} - {t.favorecido}"
    if c.historico_padrao:
        historico = f"{c.historico_padrao} - {historico}"

    if bloqueios:
        status = Status.BLOQUEADO
    elif pendencias:
        status = Status.PENDENTE
    else:
        status = Status.LIBERADO
    return Lancamento(chave, t, debito, credito, historico, status, bloqueios + pendencias, c.fonte)


class Motor:
    def __init__(
        self,
        banco: BancoDeDados,
        plano: PlanoDeContas,
        regras: ConjuntoDeRegras,
        classificador: Classificador | None = None,
        usuario: str = "sistema",
    ):
        self.banco = banco
        self.plano = plano
        self.regras = regras
        self.classificador = classificador or SemIA()
        self.usuario = usuario

    # ------------------------------------------------------------ importação
    def importar(self, caminho: str | Path, conta_bancaria: str | None = None) -> ResultadoImportacao:
        caminho = Path(caminho)
        transacoes = ler_extrato(caminho, conta_bancaria)
        hash_arquivo = hashlib.sha256(caminho.read_bytes()).hexdigest()
        db = self.banco.conexao

        anterior = db.execute(
            "SELECT id FROM lotes WHERE tipo='importacao' AND hash_arquivo=? ORDER BY id LIMIT 1",
            (hash_arquivo,),
        ).fetchone()

        repetidas_no_arquivo = {c for c, n in Counter(conteudo(t) for t in transacoes).items() if n > 1}
        chaves = calcular_chaves(transacoes)
        resultado = ResultadoImportacao(lote_id=None, lidas=len(transacoes))
        resultado.arquivo_ja_visto_no_lote = anterior["id"] if anterior else None

        with self.banco.transacao():
            cursor = db.execute(
                "INSERT INTO lotes (tipo, criado_em, usuario, descricao, hash_arquivo)"
                " VALUES ('importacao', ?, ?, ?, ?)",
                (agora(), self.usuario, caminho.name, hash_arquivo),
            )
            lote_id = cursor.lastrowid
            resultado.lote_id = lote_id

            for t, (chave, chave_conteudo, _ocorrencia) in zip(transacoes, chaves):
                if t.valor > 0:
                    resultado.total_entradas += t.valor
                else:
                    resultado.total_saidas += t.valor

                if db.execute("SELECT 1 FROM transacoes WHERE chave=?", (chave,)).fetchone():
                    resultado.ja_importadas += 1
                    continue

                alertas = []
                if conteudo(t) in repetidas_no_arquivo:
                    alertas.append(MOTIVO_DUP_ARQUIVO)
                if db.execute(
                    "SELECT 1 FROM transacoes WHERE chave_conteudo=? AND chave<>?",
                    (chave_conteudo, chave),
                ).fetchone():
                    alertas.append(MOTIVO_DUP_BANCO)

                classificacao = self._classificar(t)
                lanc = montar_lancamento(
                    chave, t, classificacao, self.plano, self.regras.conta_banco, alertas
                )
                db.execute(
                    "INSERT INTO transacoes (chave, chave_conteudo, fitid, conta_bancaria, data,"
                    " valor, historico, favorecido, documento, origem, linha, lote_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (chave, chave_conteudo, t.fitid, t.conta_bancaria, t.data.isoformat(),
                     f"{t.valor:.2f}", t.historico, t.favorecido, t.documento, t.origem,
                     t.linha, lote_id),
                )
                self._gravar_lancamento(lanc, classificacao.conta_contrapartida)
                self.banco.registrar_evento(
                    self.usuario, "importado", f"{lanc.status.value}; fonte={lanc.fonte}",
                    chave=chave, lote_id=lote_id,
                )
                resultado.novas += 1
                resultado.por_status[lanc.status] += 1

            self.banco.registrar_evento(
                self.usuario, "lote_importado",
                f"{caminho.name}: {resultado.novas} novas, {resultado.ja_importadas} já existentes",
                lote_id=lote_id,
            )
        return resultado

    def _classificar(self, t: Transacao) -> Classificacao:
        c = self.regras.classificar(t)
        if c.conta_contrapartida is not None or c.observacao.startswith("regras conflitantes"):
            return c
        sugestao = self.classificador.sugerir(t, self.plano)
        if sugestao is None:
            return c
        return Classificacao(
            sugestao.conta, None, "ia",
            f"confiança {sugestao.confianca}: {sugestao.justificativa}",
        )

    def _gravar_lancamento(self, lanc: Lancamento, contrapartida: str | None) -> None:
        self.banco.conexao.execute(
            "INSERT INTO lancamentos (chave, conta_contrapartida, conta_debito, conta_credito,"
            " historico, status, motivos, fonte, atualizado_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(chave) DO UPDATE SET conta_contrapartida=excluded.conta_contrapartida,"
            " conta_debito=excluded.conta_debito, conta_credito=excluded.conta_credito,"
            " historico=excluded.historico, status=excluded.status, motivos=excluded.motivos,"
            " fonte=excluded.fonte, atualizado_em=excluded.atualizado_em",
            (lanc.chave, contrapartida, lanc.conta_debito, lanc.conta_credito, lanc.historico,
             lanc.status.value, " | ".join(lanc.motivos), lanc.fonte, agora()),
        )

    # ------------------------------------------------------------ consulta
    def listar(self, status: Status | str | None = None) -> list[dict]:
        sql = (
            "SELECT t.chave, t.data, t.valor, t.historico AS historico_banco, t.favorecido,"
            " t.documento,"
            " t.origem, t.linha, t.conta_bancaria, l.conta_contrapartida, l.conta_debito,"
            " l.conta_credito, l.historico, l.status, l.motivos, l.fonte, l.lote_exportacao"
            " FROM transacoes t JOIN lancamentos l USING (chave)"
        )
        params: tuple = ()
        if status:
            sql += " WHERE l.status=?"
            params = (Status(status).value,)
        sql += " ORDER BY t.data, t.origem, t.linha"
        return [dict(r) for r in self.banco.conexao.execute(sql, params)]

    def _transacao(self, chave: str) -> tuple[Transacao, dict]:
        linha = self.banco.conexao.execute(
            "SELECT t.*, l.status, l.conta_contrapartida, l.fonte, l.historico AS historico_lanc"
            " FROM transacoes t JOIN lancamentos l USING (chave) WHERE chave=?",
            (chave,),
        ).fetchone()
        if linha is None:
            raise KeyError(f"lançamento {chave} não encontrado")
        t = Transacao(
            conta_bancaria=linha["conta_bancaria"], data=date.fromisoformat(linha["data"]),
            valor=Decimal(linha["valor"]), historico=linha["historico"],
            favorecido=linha["favorecido"],
            documento=linha["documento"], fitid=linha["fitid"], origem=linha["origem"],
            linha=linha["linha"],
        )
        return t, dict(linha)

    # ------------------------------------------------------------ revisão
    def aprovar(self, chave: str, conta: str | None = None, historico: str | None = None) -> Lancamento:
        """O revisor confirma (ou corrige) a classificação.

        A aprovação resolve pendências de julgamento (sugestão da IA, possível
        duplicidade). Não resolve bloqueios: conta inexistente continua bloqueada.
        """
        t, atual = self._transacao(chave)
        if atual["status"] in (Status.EXPORTADO.value, Status.DESCARTADO.value):
            raise ValueError(f"lançamento já {atual['status']}; não pode ser alterado")
        contrapartida = conta or atual["conta_contrapartida"]
        if contrapartida is None:
            raise ValueError("informe a conta de contrapartida para aprovar")
        c = Classificacao(contrapartida, None, "manual" if conta else f"{atual['fonte']}+aprovado")
        lanc = montar_lancamento(chave, t, c, self.plano, self.regras.conta_banco)
        if historico:
            lanc.historico = historico
        elif not conta:
            lanc.historico = atual["historico_lanc"]
        with self.banco.transacao():
            self._gravar_lancamento(lanc, contrapartida)
            self.banco.registrar_evento(
                self.usuario, "aprovado",
                f"contrapartida={contrapartida}; resultado={lanc.status.value}", chave=chave,
            )
        return lanc

    def descartar(self, chave: str, motivo: str) -> None:
        if not motivo.strip():
            raise ValueError("informe o motivo do descarte")
        _, atual = self._transacao(chave)
        if atual["status"] == Status.EXPORTADO.value:
            raise ValueError("lançamento já exportado; corrija no sistema contábil")
        with self.banco.transacao():
            self.banco.conexao.execute(
                "UPDATE lancamentos SET status=?, motivos=?, atualizado_em=? WHERE chave=?",
                (Status.DESCARTADO.value, f"descartado: {motivo}", agora(), chave),
            )
            self.banco.registrar_evento(self.usuario, "descartado", motivo, chave=chave)

    # ------------------------------------------------------------ exportação
    def exportar(self, destino: str | Path, exportador=None) -> tuple[int | None, int]:
        """Exporta só lançamentos liberados e ainda não exportados.

        Exportar duas vezes não repete lançamentos: o segundo arquivo sai vazio.
        Devolve (id do lote de exportação, quantidade).
        """
        exportador = exportador or ExportadorCSVGenerico(self.plano)
        liberados = self.listar(Status.LIBERADO)
        if not liberados:
            return None, 0
        db = self.banco.conexao
        with self.banco.transacao():
            lote_id = db.execute(
                "INSERT INTO lotes (tipo, criado_em, usuario, descricao)"
                " VALUES ('exportacao', ?, ?, ?)",
                (agora(), self.usuario, Path(destino).name),
            ).lastrowid
            for item in liberados:
                db.execute(
                    "UPDATE lancamentos SET status=?, lote_exportacao=?, atualizado_em=?"
                    " WHERE chave=? AND status=?",
                    (Status.EXPORTADO.value, lote_id, agora(), item["chave"], Status.LIBERADO.value),
                )
            # O arquivo é escrito dentro da transação: se a escrita falhar,
            # os lançamentos voltam a "liberado".
            exportador.escrever(liberados, destino)
            self.banco.registrar_evento(
                self.usuario, "exportado", f"{len(liberados)} lançamentos em {destino}",
                lote_id=lote_id,
            )
        return lote_id, len(liberados)

    def lotes_exportacao(self) -> list[dict]:
        """Exportações já feitas, da mais recente para a mais antiga."""
        return [dict(r) for r in self.banco.conexao.execute(
            "SELECT lo.id, lo.criado_em, lo.usuario, COUNT(la.chave) AS quantidade"
            " FROM lotes lo LEFT JOIN lancamentos la ON la.lote_exportacao = lo.id"
            " WHERE lo.tipo='exportacao' GROUP BY lo.id ORDER BY lo.id DESC"
        )]

    def reexportar(self, lote_id: int, destino: str | Path, exportador=None,
                   registrar: bool = True) -> int:
        """Gera de novo o arquivo de uma exportação anterior, idêntico ao original.

        Não muda a situação de nenhum lançamento. Serve para recuperar um
        arquivo perdido ou que não foi baixado, sem liberar os lançamentos
        para uma segunda exportação (o que criaria duplicidade no sistema
        contábil).
        """
        exportador = exportador or ExportadorCSVGenerico(self.plano)
        itens = [i for i in self.listar(Status.EXPORTADO) if i["lote_exportacao"] == lote_id]
        if not itens:
            raise KeyError(f"lote de exportação {lote_id} não encontrado")
        exportador.escrever(itens, destino)
        if registrar:
            self.banco.registrar_evento(
                self.usuario, "reexportado", f"lote {lote_id} regerado em {destino}",
                lote_id=lote_id,
            )
            self.banco.conexao.commit()
        return len(itens)
