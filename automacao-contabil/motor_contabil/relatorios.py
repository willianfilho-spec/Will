"""Relatórios em PDF para análise e auditoria humana.

Dois relatórios, ambos gerados a partir do que o sistema registrou, sem
recalcular nada por fora:

1. ``relatorio_processamento``: o que o motor fez num período. Volume
   importado, situação de cada lançamento, quanto foi classificado sem
   intervenção, o que exigiu revisão, pendências, bloqueios, descartes,
   totais por conta, lotes (com hash) e a trilha de auditoria.
2. ``relatorio_conciliacao``: a conferência do banco (extrato x arquivos
   importados no Fortes), com saldo por mês e as sobras de cada lado.

Os dois terminam com um quadro de revisão para o contador assinar. Cada
relatório traz um código de conferência (SHA-256 dos dados usados), para
mostrar que dois relatórios com o mesmo código vieram dos mesmos dados.

Requer o pacote ``reportlab`` (importado só quando um relatório é pedido).
"""

from __future__ import annotations

import hashlib
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from .modelo import Status
from .plano_contas import PlanoDeContas

VERSAO = "fase 1 (piloto interno)"

ROTULO_STATUS = {
    Status.LIBERADO.value: "Liberado (aguardando exportação)",
    Status.EXPORTADO.value: "Exportado para o Fortes",
    Status.PENDENTE.value: "Pendente de revisão",
    Status.BLOQUEADO.value: "Bloqueado",
    Status.DESCARTADO.value: "Descartado pelo revisor",
}


# ------------------------------------------------------------------ formatação

def brl(valor: Decimal | str | int) -> str:
    v = Decimal(str(valor))
    inteiro, _, dec = f"{abs(v):.2f}".partition(".")
    inteiro = f"{int(inteiro):,}".replace(",", ".")
    return f"{'-' if v < 0 else ''}R$ {inteiro},{dec}"


def data_br(texto: str | date) -> str:
    t = texto.isoformat() if isinstance(texto, date) else str(texto)
    return f"{t[8:10]}/{t[5:7]}/{t[0:4]}" if len(t) >= 10 else t


def _quando(texto: str) -> str:
    return f"{data_br(texto)} {texto[11:16]}" if len(texto) >= 16 else data_br(texto)


def codigo_conferencia(dados) -> str:
    bruto = json.dumps(dados, sort_keys=True, default=str, ensure_ascii=False).encode()
    return hashlib.sha256(bruto).hexdigest()


# ------------------------------------------------------------------ dados do processamento

@dataclass
class DadosProcessamento:
    empresa_nome: str
    empresa_cnpj: str
    conta_banco: str
    inicio: date
    fim: date
    lancamentos: list[dict]
    eventos: list[dict]
    lotes: list[dict]
    plano: PlanoDeContas | None = None

    def chaves(self) -> set[str]:
        return {l["chave"] for l in self.lancamentos}


def coletar_processamento(conexao, empresa_nome: str, empresa_cnpj: str, conta_banco: str,
                          inicio: date, fim: date, plano: PlanoDeContas | None = None) -> DadosProcessamento:
    """Lê do banco da empresa os lançamentos com data no período e o que se refere a eles."""
    lancamentos = [dict(r) for r in conexao.execute(
        "SELECT t.chave, t.data, t.valor, t.historico AS historico_banco, t.documento, t.origem,"
        " t.linha, t.lote_id AS lote_importacao, l.conta_contrapartida, l.conta_debito,"
        " l.conta_credito, l.historico, l.status, l.motivos, l.fonte, l.lote_exportacao"
        " FROM transacoes t JOIN lancamentos l USING (chave)"
        " WHERE t.data BETWEEN ? AND ? ORDER BY t.data, t.origem, t.linha",
        (inicio.isoformat(), fim.isoformat()),
    )]
    chaves = {l["chave"] for l in lancamentos}
    lotes_ids = {l["lote_importacao"] for l in lancamentos} | {
        l["lote_exportacao"] for l in lancamentos if l["lote_exportacao"]}
    eventos = [dict(r) for r in conexao.execute("SELECT * FROM eventos ORDER BY id")
               if r["chave"] in chaves or (r["chave"] is None and r["lote_id"] in lotes_ids)]
    lotes = []
    for lid in sorted(x for x in lotes_ids if x is not None):
        r = conexao.execute("SELECT * FROM lotes WHERE id=?", (lid,)).fetchone()
        if r is None:
            continue
        lote = dict(r)
        if lote["tipo"] == "exportacao" and not lote.get("hash_arquivo"):
            arq = conexao.execute("SELECT conteudo FROM arquivos_exportacao WHERE lote_id=?",
                                  (lid,)).fetchone()
            if arq is not None:
                lote["hash_arquivo"] = hashlib.sha256(arq["conteudo"]).hexdigest()
        lote["quantidade"] = sum(
            1 for l in lancamentos
            if (l["lote_importacao"] if lote["tipo"] == "importacao" else l["lote_exportacao"]) == lid)
        lotes.append(lote)
    return DadosProcessamento(empresa_nome, empresa_cnpj, conta_banco, inicio, fim,
                              lancamentos, eventos, lotes, plano)


@dataclass
class Indicadores:
    total: int
    entradas: Decimal
    saidas: Decimal
    por_status: Counter
    valor_por_status: dict
    automaticos: int          # classificados por regra e nunca tocados pelo revisor
    revisados: int            # aprovados ou descartados por uma pessoa
    corrigidos: int           # aprovados com conta diferente da proposta
    em_aberto: int            # pendentes + bloqueados

    @property
    def taxa_automatica(self) -> float:
        return self.automaticos / self.total if self.total else 0.0


def calcular_indicadores(d: DadosProcessamento) -> Indicadores:
    por_status: Counter = Counter(l["status"] for l in d.lancamentos)
    valor_por_status: dict = defaultdict(lambda: Decimal("0"))
    for l in d.lancamentos:
        valor_por_status[l["status"]] += abs(Decimal(l["valor"]))
    acoes_por_chave: dict[str, set] = defaultdict(set)
    for e in d.eventos:
        if e["chave"]:
            acoes_por_chave[e["chave"]].add(e["acao"])
    revisados = {c for c, a in acoes_por_chave.items() if a & {"aprovado", "descartado"}}
    corrigidos = sum(1 for l in d.lancamentos if l["fonte"] == "manual")
    automaticos = sum(
        1 for l in d.lancamentos
        if l["chave"] not in revisados and l["fonte"].startswith("regra:")
        and l["status"] in (Status.LIBERADO.value, Status.EXPORTADO.value))
    return Indicadores(
        total=len(d.lancamentos),
        entradas=sum((Decimal(l["valor"]) for l in d.lancamentos if Decimal(l["valor"]) > 0), Decimal("0")),
        saidas=sum((Decimal(l["valor"]) for l in d.lancamentos if Decimal(l["valor"]) < 0), Decimal("0")),
        por_status=por_status,
        valor_por_status=dict(valor_por_status),
        automaticos=automaticos,
        revisados=len(revisados & d.chaves()),
        corrigidos=corrigidos,
        em_aberto=por_status[Status.PENDENTE.value] + por_status[Status.BLOQUEADO.value],
    )


def totais_por_conta(d: DadosProcessamento) -> list[tuple[str, str, int, Decimal, Decimal]]:
    """(conta, descrição, quantidade, entradas, saídas) da contrapartida, só liberados e exportados."""
    soma: dict[str, list] = defaultdict(lambda: [0, Decimal("0"), Decimal("0")])
    for l in d.lancamentos:
        if l["status"] not in (Status.LIBERADO.value, Status.EXPORTADO.value):
            continue
        v = Decimal(l["valor"])
        s = soma[l["conta_contrapartida"] or "(sem conta)"]
        s[0] += 1
        if v > 0:
            s[1] += v
        else:
            s[2] += v
    linhas = []
    for conta, (n, ent, sai) in sorted(soma.items(), key=lambda kv: kv[1][2]):
        c = d.plano.get(conta) if d.plano else None
        desc = c.descricao if c else ""
        if c and c.codigo_exportacao and c.codigo_exportacao != conta:
            desc = f"{desc} (red. {c.codigo_exportacao})"
        linhas.append((conta, desc, n, ent, sai))
    return linhas


# ------------------------------------------------------------------ montagem do PDF

class _Documento:
    """Envoltório fino sobre o ReportLab, com o padrão visual dos relatórios."""

    def __init__(self, titulo: str, empresa: str, cnpj: str, periodo: str, usuario: str):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm

        self.c, self.mm, self.A4 = colors, mm, A4
        self.titulo, self.empresa, self.cnpj, self.periodo, self.usuario = titulo, empresa, cnpj, periodo, usuario
        self.emitido = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.bordo = colors.HexColor("#7a1f3d")
        self.tinta = colors.HexColor("#1f2937")
        base = dict(fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=self.tinta)
        self.s = {
            "p": ParagraphStyle("p", spaceAfter=4, **base),
            "pequeno": ParagraphStyle("pq", **{**base, "fontSize": 7.2, "leading": 9.2}),
            "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=19,
                                 textColor=self.bordo, spaceAfter=2),
            "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14,
                                 textColor=self.bordo, spaceBefore=10, spaceAfter=4),
            "cel": ParagraphStyle("cel", **{**base, "fontSize": 7.4, "leading": 9.2}),
            "celn": ParagraphStyle("celn", alignment=2, **{**base, "fontSize": 7.4, "leading": 9.2}),
            "cab": ParagraphStyle("cab", fontName="Helvetica-Bold", fontSize=7.4, leading=9.2,
                                  textColor=colors.white),
            "cabn": ParagraphStyle("cabn", fontName="Helvetica-Bold", fontSize=7.4, leading=9.2,
                                   textColor=colors.white, alignment=2),
        }
        self.fluxo: list = []
        self.largura = A4[0] - 30 * mm

    # -- blocos
    def esc(self, t) -> str:
        from xml.sax.saxutils import escape
        return escape(str(t if t is not None else ""))

    def titulo_doc(self, subtitulo: str):
        from reportlab.platypus import Paragraph, Spacer
        self.fluxo += [
            Paragraph(self.esc(self.titulo), self.s["h1"]),
            Paragraph(self.esc(subtitulo), self.s["p"]),
            Spacer(1, 4),
        ]
        self.tabela(
            [["Empresa", "CNPJ", "Período", "Emitido em", "Emitido por"],
             [self.empresa, self.cnpj, self.periodo, self.emitido, self.usuario]],
            larguras=[0.32, 0.18, 0.2, 0.15, 0.15])

    def secao(self, texto: str):
        from reportlab.platypus import Paragraph
        p = Paragraph(self.esc(texto), self.s["h2"])
        p.keepWithNext = True
        self.fluxo.append(p)

    def paragrafo(self, html: str, estilo: str = "p"):
        from reportlab.platypus import Paragraph
        self.fluxo.append(Paragraph(html, self.s[estilo]))

    def aviso(self, texto: str, ok: bool):
        from reportlab.platypus import Table, TableStyle, Paragraph
        cor = self.c.HexColor("#166534") if ok else self.c.HexColor("#b91c1c")
        fundo = self.c.HexColor("#dcfce7") if ok else self.c.HexColor("#fee2e2")
        t = Table([[Paragraph(f"<b>{self.esc(texto)}</b>", self.s["p"])]], colWidths=[self.largura])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fundo),
                               ("BOX", (0, 0), (-1, -1), 0.8, cor),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        self.fluxo.append(t)

    def tabela(self, linhas: list[list], larguras: list[float] | None = None,
               numericas: Iterable[int] = (), destaque: Iterable[int] = (), vazio: str = "Nenhum."):
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        if len(linhas) <= 1:
            self.paragrafo(f"<i>{self.esc(vazio)}</i>")
            return
        numericas = set(numericas)
        dados = []
        for i, linha in enumerate(linhas):
            dados.append([
                Paragraph(self.esc(v), self.s[("cabn" if j in numericas else "cab") if i == 0
                                              else ("celn" if j in numericas else "cel")])
                for j, v in enumerate(linha)])
        n = len(linhas[0])
        larguras = larguras or [1 / n] * n
        t = Table(dados, colWidths=[self.largura * x for x in larguras], repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), self.bordo),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, self.c.HexColor("#d1d5db")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [self.c.white, self.c.HexColor("#faf5f7")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for i in destaque:
            estilo.append(("BACKGROUND", (0, i), (-1, i), self.c.HexColor("#fff7ed")))
        t.setStyle(TableStyle(estilo))
        self.fluxo += [t, Spacer(1, 4)]

    def quadro_revisao(self, codigo: str):
        from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle
        linhas = [
            ["Conclusão do revisor", ""],
            ["( ) Aprovado sem ressalvas    ( ) Aprovado com ressalvas    ( ) Reprovado", ""],
            ["Observações:\n\n\n", ""],
            ["Revisado por (nome e CRC):", "Data e assinatura:"],
            ["\n\n", ""],
        ]
        dados = [[Paragraph(self.esc(a).replace("\n", "<br/>"), self.s["p"]),
                  Paragraph(self.esc(b), self.s["p"])] for a, b in linhas]
        t = Table(dados, colWidths=[self.largura * 0.6, self.largura * 0.4])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, self.bordo),
            ("SPAN", (0, 0), (1, 0)), ("SPAN", (0, 1), (1, 1)), ("SPAN", (0, 2), (1, 2)),
            ("BACKGROUND", (0, 0), (-1, 0), self.c.HexColor("#faf5f7")),
            ("LINEBELOW", (0, 2), (-1, 2), 0.3, self.c.HexColor("#d1d5db")),
        ]))
        self.fluxo.append(KeepTogether([
            Paragraph("Revisão humana", self.s["h2"]), t, Spacer(1, 6),
            Paragraph(
                f"Código de conferência (SHA-256 dos dados usados neste relatório): {codigo}. "
                "Relatórios gerados a partir dos mesmos dados têm o mesmo código.", self.s["pequeno"]),
            Paragraph(
                "Este relatório apoia a revisão e não a substitui. O sistema classifica por regras "
                "aprovadas pelo contador; sugestões de inteligência artificial ficam sempre pendentes "
                "até aprovação humana.", self.s["pequeno"]),
        ]))

    def gerar(self) -> bytes:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
        mm = self.mm
        buf = io.BytesIO()

        def rodape(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 6.8)
            canvas.setFillColor(self.c.HexColor("#6b7280"))
            canvas.drawString(15 * mm, 9 * mm,
                              f"{self.titulo} | {self.empresa} | {self.periodo} | Conciliador Fortes, {VERSAO}")
            canvas.drawRightString(self.A4[0] - 15 * mm, 9 * mm, f"página {doc.page}")
            canvas.restoreState()

        doc = BaseDocTemplate(buf, pagesize=self.A4, leftMargin=15 * mm, rightMargin=15 * mm,
                              topMargin=14 * mm, bottomMargin=16 * mm, title=self.titulo,
                              author="Conciliador Fortes", subject=f"{self.empresa} - {self.periodo}")
        doc.addPageTemplates([PageTemplate(id="p", onPage=rodape, frames=[
            Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")])])
        doc.build(self.fluxo)
        return buf.getvalue()


# ------------------------------------------------------------------ relatório 1: processamento

def relatorio_processamento(d: DadosProcessamento, usuario: str) -> bytes:
    ind = calcular_indicadores(d)
    periodo = f"{data_br(d.inicio)} a {data_br(d.fim)}"
    doc = _Documento("Relatório de processamento e revisão", d.empresa_nome, d.empresa_cnpj, periodo, usuario)
    doc.titulo_doc("Lançamentos gerados a partir dos extratos, situação de cada um e trilha de auditoria.")

    doc.secao("1. Resumo")
    if not ind.total:
        doc.paragrafo("<i>Nenhuma transação importada com data neste período.</i>")
    pct = lambda n: f"{(100 * n / ind.total):.1f}%" if ind.total else "-"  # noqa: E731
    doc.tabela([
        ["Indicador", "Quantidade", "Percentual", "Valor"],
        ["Transações no período", str(ind.total), "100%" if ind.total else "-",
         f"entradas {brl(ind.entradas)} / saídas {brl(ind.saidas)}"],
        ["Classificadas por regra, sem intervenção", str(ind.automaticos), pct(ind.automaticos), ""],
        ["Revisadas por uma pessoa (aprovadas ou descartadas)", str(ind.revisados), pct(ind.revisados), ""],
        ["  das quais com conta corrigida pelo revisor", str(ind.corrigidos), pct(ind.corrigidos), ""],
        ["Em aberto (pendentes + bloqueados)", str(ind.em_aberto), pct(ind.em_aberto), ""],
    ], larguras=[0.46, 0.12, 0.12, 0.30], numericas=[1, 2])
    doc.tabela(
        [["Situação", "Quantidade", "Valor absoluto"]]
        + [[ROTULO_STATUS[s.value], str(ind.por_status.get(s.value, 0)),
            brl(ind.valor_por_status.get(s.value, Decimal("0")))]
           for s in (Status.EXPORTADO, Status.LIBERADO, Status.PENDENTE, Status.BLOQUEADO, Status.DESCARTADO)],
        larguras=[0.5, 0.2, 0.3], numericas=[1, 2])
    if ind.em_aberto:
        doc.aviso(f"Há {ind.em_aberto} lançamento(s) em aberto. O período não está pronto para fechamento.", False)
    elif ind.total:
        doc.aviso("Nenhum lançamento em aberto no período.", True)

    def lista(status: str, titulo: str, vazio: str):
        doc.secao(titulo)
        itens = [l for l in d.lancamentos if l["status"] == status]
        doc.tabela(
            [["Data", "Valor", "Histórico do banco", "Motivo", "Origem"]]
            + [[data_br(l["data"]), brl(l["valor"]), l["historico_banco"], l["motivos"],
                f"{l['origem']}:{l['linha']}"] for l in itens],
            larguras=[0.09, 0.12, 0.35, 0.26, 0.18], numericas=[1], vazio=vazio)

    lista(Status.PENDENTE.value, "2. Pendentes de revisão", "Nenhum lançamento pendente.")
    lista(Status.BLOQUEADO.value, "3. Bloqueados (precisam de correção no plano ou nas regras)",
          "Nenhum lançamento bloqueado.")
    lista(Status.DESCARTADO.value, "4. Descartados pelo revisor", "Nenhum descarte.")

    doc.secao("5. Revisões feitas por pessoas")
    revisoes = [e for e in d.eventos if e["acao"] in ("aprovado", "descartado")]
    por_chave = {l["chave"]: l for l in d.lancamentos}
    doc.tabela(
        [["Quando", "Quem", "Ação", "Lançamento", "Detalhe"]]
        + [[_quando(e["quando"]), e["usuario"], e["acao"],
            (f"{data_br(por_chave[e['chave']]['data'])} {brl(por_chave[e['chave']]['valor'])} "
             f"{por_chave[e['chave']]['historico_banco'][:40]}") if e["chave"] in por_chave else e["chave"],
            e["detalhe"]] for e in revisoes],
        larguras=[0.12, 0.1, 0.09, 0.37, 0.32], vazio="Nenhuma revisão registrada.")

    doc.secao("6. Totais por conta de contrapartida (liberados e exportados)")
    contas = totais_por_conta(d)
    doc.tabela(
        [["Conta", "Descrição", "Qtde.", "Entradas", "Saídas"]]
        + [[c, desc, str(n), brl(e), brl(s)] for c, desc, n, e, s in contas]
        + ([["Total", "", str(sum(x[2] for x in contas)), brl(sum((x[3] for x in contas), Decimal(0))),
             brl(sum((x[4] for x in contas), Decimal(0)))]] if contas else []),
        larguras=[0.2, 0.38, 0.08, 0.17, 0.17], numericas=[2, 3, 4],
        destaque=[len(contas) + 1] if contas else [], vazio="Nenhum lançamento liberado ou exportado.")

    doc.secao("7. Lotes de importação e exportação")
    doc.tabela(
        [["Lote", "Tipo", "Quando", "Quem", "Arquivo", "Lanç. do período", "SHA-256"]]
        + [[str(l["id"]), l["tipo"], _quando(l["criado_em"]), l["usuario"], l["descricao"],
            str(l["quantidade"]), (l.get("hash_arquivo") or "")[:16]] for l in d.lotes],
        larguras=[0.06, 0.1, 0.12, 0.1, 0.32, 0.12, 0.18], numericas=[0, 5],
        vazio="Nenhum lote.")
    doc.paragrafo("O SHA-256 (16 primeiros caracteres) identifica o arquivo exato importado ou entregue ao "
                  "Fortes. O arquivo de cada exportação fica guardado e pode ser baixado de novo, idêntico.",
                  "pequeno")

    doc.secao("8. Trilha de auditoria")
    doc.tabela(
        [["#", "Quando", "Quem", "Ação", "Detalhe"]]
        + [[str(e["id"]), _quando(e["quando"]), e["usuario"], e["acao"], e["detalhe"]] for e in d.eventos],
        larguras=[0.06, 0.13, 0.11, 0.11, 0.59], numericas=[0], vazio="Nenhum evento.")

    codigo = codigo_conferencia({"lanc": d.lancamentos, "eventos": d.eventos, "lotes": d.lotes,
                                 "inicio": d.inicio, "fim": d.fim})
    doc.quadro_revisao(codigo)
    return doc.gerar()


# ------------------------------------------------------------------ relatório 2: conciliação

def relatorio_conciliacao(empresa_nome: str, empresa_cnpj: str, banco: str, linhas, confronto,
                          usuario: str, arquivo_extrato: str = "", arquivos_importados: Iterable[str] = (),
                          dias_conferidos: int | None = None, movimentos: int | None = None) -> bytes:
    """``linhas`` e ``confronto`` vêm de ``conciliacao.resumo_mensal`` e ``conciliacao.confrontar``."""
    from .conciliacao import efeito_no_banco

    arquivos_importados = list(arquivos_importados)
    periodo = f"{data_br(min(l.fim for l in linhas).replace(day=1))} a {data_br(max(l.fim for l in linhas))}" \
        if linhas else "-"
    doc = _Documento("Relatório de conferência do banco", empresa_nome, empresa_cnpj, periodo, usuario)
    doc.titulo_doc("Extrato bancário x lançamentos importados no Fortes: saldo por mês e movimento a movimento.")

    ok = all(l.diferenca == 0 for l in linhas) and not confronto.so_no_extrato \
        and not confronto.so_na_contabilidade
    doc.secao("1. Resultado")
    doc.aviso("Conciliado: saldo igual em todos os meses e nenhuma sobra." if ok else
              "Não conciliado: há diferença de saldo ou movimentos sem par (ver seções 3 e 4).", ok)
    doc.tabela([
        ["Item", "Valor"],
        ["Conta do banco (código reduzido)", banco],
        ["Extrato", arquivo_extrato or "-"],
        ["Movimentos no extrato", str(movimentos if movimentos is not None else "-")],
        ["Saldos diários do extrato conferidos com a soma dos movimentos",
         str(dias_conferidos if dias_conferidos is not None else "-")],
        ["Arquivos do Fortes considerados", ", ".join(arquivos_importados) or "-"],
        ["Movimentos pareados (mesma data, mesmo valor, banco na partida certa)", str(confronto.pareados)],
        ["Só no extrato", str(len(confronto.so_no_extrato))],
        ["Só na contabilidade", str(len(confronto.so_na_contabilidade))],
    ], larguras=[0.55, 0.45])

    doc.secao("2. Saldo por mês")
    doc.tabela(
        [["Mês", "Fim", "Extrato", "Contábil", "Diferença", "Só extrato", "Só contáb."]]
        + [[l.mes, data_br(l.fim), brl(l.saldo_extrato), brl(l.saldo_contabil), brl(l.diferenca),
            str(l.so_extrato), str(l.so_contabil)] for l in linhas],
        larguras=[0.1, 0.12, 0.17, 0.17, 0.16, 0.14, 0.14], numericas=[2, 3, 4, 5, 6],
        destaque=[i + 1 for i, l in enumerate(linhas) if l.diferenca or l.so_extrato or l.so_contabil])
    doc.paragrafo("Saldo igual com sobras dos dois lados indica erros que se compensam (por exemplo, "
                  "lançamento com data errada) e não é tratado como conciliado.", "pequeno")

    doc.secao("3. Só no extrato (falta lançar, ou foi lançado com data ou valor diferente)")
    doc.tabela(
        [["Data", "Valor", "Histórico", "Documento"]]
        + [[data_br(t.data), brl(t.valor), t.historico, t.documento or ""] for t in confronto.so_no_extrato],
        larguras=[0.1, 0.14, 0.56, 0.2], numericas=[1], vazio="Nenhum.")

    doc.secao("4. Só na contabilidade (lançado sem movimento correspondente no extrato)")
    doc.tabela(
        [["Data", "Efeito no banco", "Débito", "Crédito", "Histórico", "Origem"]]
        + [[data_br(a.data), brl(efeito_no_banco(a, banco)), a.debito, a.credito, a.historico,
            f"{a.origem}:{a.linha}"] for a in confronto.so_na_contabilidade],
        larguras=[0.09, 0.13, 0.08, 0.08, 0.44, 0.18], numericas=[1], vazio="Nenhum.")

    doc.secao("5. Limites desta conferência")
    doc.paragrafo("A contabilidade é representada pelos arquivos de importação informados, não pelo razão "
                  "emitido pelo Fortes. Lançamento feito, apagado ou alterado à mão no Fortes não aparece "
                  "aqui; para isso, compare também o saldo da conta do banco no balancete.")

    codigo = codigo_conferencia({
        "linhas": [l.__dict__ for l in linhas],
        "so_extrato": [t.__dict__ for t in confronto.so_no_extrato],
        "so_contabil": [a.__dict__ for a in confronto.so_na_contabilidade],
        "pareados": confronto.pareados, "banco": banco,
    })
    doc.quadro_revisao(codigo)
    return doc.gerar()
