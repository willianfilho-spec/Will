"""Leitor do extrato Itaú Empresas em PDF ("Entradas e Saídas").

Adaptado do extrator da skill de conciliação do escritório, já usado na
primeira empresa do piloto. Cada movimento vira uma Transacao. As linhas
"SALDO TOTAL DISPONÍVEL DIA" não viram movimento: servem para conferir o
próprio arquivo. Se saldo do dia anterior + movimentos do dia não der o saldo
impresso, a leitura é recusada, porque algum movimento foi lido errado.

Requer o pacote opcional `pdfplumber` (ver requirements.txt). As posições das
colunas são as do leiaute atual do Itaú; outro banco precisa de outro leitor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..modelo import Transacao

DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
DINHEIRO = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
DOC = re.compile(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{3}\.\d{3}\.\d{3}-\d{2})")
X_DATA_MAX = 80
X_HIST_MAX = 222
X_VALOR_MAX = 515
X_DINHEIRO_MIN = 455
DESVIO_MAX = 7.5
PREFIXOS = ("PIX ENVIADO", "PIX RECEBIDO", "PAGAMENTOS", "BOLETO PAGO", "RECEBIMENTOS",
            "SISPAG FORNECEDORES")


@dataclass
class ExtratoLido:
    transacoes: list[Transacao]
    saldos: dict[date, Decimal]   # saldo impresso no fim de cada dia
    dias_conferidos: int


def _br(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").replace(",", "."))


def _linhas_do_pdf(caminho: Path) -> list[dict]:
    try:
        import pdfplumber
    except ImportError as erro:
        raise ValueError(
            "Para ler extrato em PDF, instale o pacote pdfplumber (pip install -r requirements.txt)."
        ) from erro
    linhas: list[dict] = []
    sobra: list[dict] = []
    with pdfplumber.open(caminho) as pdf:
        for pagina, pg in enumerate(pdf.pages, 1):
            palavras = pg.extract_words(keep_blank_chars=False, use_text_flow=False)
            ancoras = sorted((w for w in palavras if DATA.match(w["text"]) and w["x0"] < X_DATA_MAX),
                             key=lambda w: w["top"])
            if not ancoras:
                continue
            ys = [a["top"] for a in ancoras]
            grupos: dict[int, list[dict]] = {i: [] for i in range(len(ancoras))}
            grupos[0].extend(sobra)
            sobra = []
            for w in palavras:
                if w in ancoras or (pagina == 1 and w["top"] < max(ys[0] - 40, 190)):
                    continue
                if w["text"].startswith(("aviso:", "novos", "atualizado", "Em", "caso", "0728")) \
                        and w["top"] > ys[-1] + 40:
                    continue
                j = min(range(len(ys)), key=lambda k: abs(ys[k] - w["top"]))
                if j == len(ys) - 1 and w["top"] - ys[j] > DESVIO_MAX:
                    sobra.append(w)   # lançamento que continua na página seguinte
                    continue
                grupos[j].append(w)
            for j, ancora in enumerate(ancoras):
                hist, razao, valor, saldo = [], [], None, None
                for w in sorted(grupos[j], key=lambda w: (w["top"], w["x0"])):
                    t = w["text"]
                    if w["x0"] >= X_DINHEIRO_MIN and DINHEIRO.match(t):
                        if w["x1"] <= X_VALOR_MAX:
                            valor = _br(t)
                        else:
                            saldo = _br(t)
                    elif w["x0"] < X_HIST_MAX:
                        hist.append(t)
                    else:
                        razao.append(t)
                contraparte = " ".join(razao)
                m = DOC.search(contraparte)
                documento = m.group(1) if m else None
                if m:
                    contraparte = (contraparte[:m.start()] + " " + contraparte[m.end():])
                linhas.append({
                    "data": datetime.strptime(ancora["text"], "%d/%m/%Y").date(),
                    "historico": " ".join(hist).strip(),
                    "contraparte": re.sub(r"\s+", " ", contraparte).strip(),
                    "documento": documento, "valor": valor, "saldo": saldo,
                    "pagina": pagina, "ordem": len(linhas),
                })
    return linhas


def _normalizar(linha: dict) -> dict:
    """Leiaute antigo: 'PIX ENVIADO PIX ENVIADO NOME' ou 'NOME PIX ENVIADO PIX ENVIADO'."""
    h = linha["historico"]
    for p in PREFIXOS:
        m = re.match(rf"^{re.escape(p)}\s+{re.escape(p)}\s*(.*)$", h)
        if m:
            linha["historico"] = p
            linha["contraparte"] = linha["contraparte"] or m.group(1).strip()
            return linha
    m = re.match(r"^(.*?)\s+(PIX ENVIADO|PIX RECEBIDO)\s+\2\s*$", h)
    if m and m.group(1):
        linha["historico"] = m.group(2)
        linha["contraparte"] = linha["contraparte"] or m.group(1).strip()
    return linha


def separar(linhas: list[dict]) -> tuple[list[dict], dict[date, Decimal]]:
    movimentos, saldos = [], {}
    for linha in linhas:
        h = linha["historico"]
        if h.startswith(("SALDO TOTAL DISPONÍVEL DIA", "SALDO EM CONTA CORRENTE")):
            if linha["saldo"] is not None:
                saldos[linha["data"]] = linha["saldo"]
        elif h.startswith("SALDO ANTERIOR"):
            saldos.setdefault(linha["data"], linha["saldo"] or Decimal("0.00"))
        elif linha["valor"] is not None:
            movimentos.append(_normalizar(linha))
    movimentos.sort(key=lambda r: (r["data"], r["pagina"], r["ordem"]))
    return movimentos, saldos


def conferir_saldos_diarios(movimentos: list[dict], saldos: dict[date, Decimal]) -> tuple[int, list[str]]:
    """Saldo do dia anterior + movimentos do período = saldo impresso. Devolve (dias, divergências)."""
    por_dia: dict[date, Decimal] = {}
    for m in movimentos:
        por_dia[m["data"]] = por_dia.get(m["data"], Decimal("0")) + m["valor"]
    dias = sorted(saldos)
    divergencias = []
    for anterior, atual in zip(dias, dias[1:]):
        soma = sum((v for d, v in por_dia.items() if anterior < d <= atual), Decimal("0"))
        if saldos[anterior] + soma != saldos[atual]:
            divergencias.append(
                f"{atual.strftime('%d/%m/%Y')}: saldo anterior {saldos[anterior]} + movimentos {soma}"
                f" = {saldos[anterior] + soma}, mas o extrato imprime {saldos[atual]}"
            )
    if dias and any(d < dias[0] for d in por_dia):
        divergencias.append("há movimentos antes do primeiro saldo impresso")
    return max(len(dias) - 1, 0), divergencias


def ler_itau_pdf_completo(caminho: str | Path, conta_bancaria: str) -> ExtratoLido:
    caminho = Path(caminho)
    movimentos, saldos = separar(_linhas_do_pdf(caminho))
    if not movimentos or not saldos:
        raise ValueError(f"{caminho.name}: não reconheci o extrato Itaú (Entradas e Saídas)")
    dias, divergencias = conferir_saldos_diarios(movimentos, saldos)
    if divergencias:
        raise ValueError(
            f"{caminho.name}: a soma dos movimentos não confere com o saldo impresso. "
            "Nada foi importado. Primeiras divergências:\n- " + "\n- ".join(divergencias[:5])
        )
    transacoes = [
        Transacao(
            conta_bancaria=conta_bancaria, data=m["data"], valor=m["valor"],
            historico=" ".join(p for p in (m["historico"], m["contraparte"]) if p),
            documento=m["documento"], origem=caminho.name, linha=i,
        )
        for i, m in enumerate(movimentos, 1)
    ]
    return ExtratoLido(transacoes, saldos, dias)


def ler_itau_pdf(caminho: str | Path, conta_bancaria: str) -> list[Transacao]:
    return ler_itau_pdf_completo(caminho, conta_bancaria).transacoes
