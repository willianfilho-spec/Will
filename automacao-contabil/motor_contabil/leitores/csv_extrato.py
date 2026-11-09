"""Leitor de extratos em CSV/planilha exportada como CSV.

Aceita duas formas comuns:
  - uma coluna de valor com sinal (negativo = saída);
  - colunas separadas de entrada (crédito) e saída (débito).

Os nomes de coluna são reconhecidos por sinônimos (ver ALIASES). Quando o
banco usar um nome diferente, passe `mapa_colunas`.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from ..modelo import Transacao
from ..texto import normalizar, para_decimal

ALIASES = {
    "data": {"DATA", "DATA LANCAMENTO", "DATA MOVIMENTO", "DT", "DATE"},
    "historico": {"HISTORICO", "DESCRICAO", "LANCAMENTO", "MEMO", "DESCRIPTION"},
    "valor": {"VALOR", "VALOR (R$)", "VALOR R$", "AMOUNT"},
    "entrada": {"ENTRADA", "CREDITO", "CREDITOS", "ENTRADAS"},
    "saida": {"SAIDA", "DEBITO", "DEBITOS", "SAIDAS"},
    "documento": {"DOCUMENTO", "DOC", "NUMERO DOCUMENTO", "Nº DOCUMENTO"},
    "id": {"ID", "IDENTIFICADOR", "ID TRANSACAO", "FITID"},
}


def _data(bruto: str) -> date:
    bruto = bruto.strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(bruto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {bruto!r}")


def _ler_texto(caminho: Path) -> str:
    conteudo = caminho.read_bytes()
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1")


def ler_csv(
    caminho: str | Path,
    conta_bancaria: str,
    mapa_colunas: dict[str, str] | None = None,
) -> list[Transacao]:
    caminho = Path(caminho)
    texto = _ler_texto(caminho)
    try:
        dialeto = csv.Sniffer().sniff(texto[:2000], delimiters=";,\t")
    except csv.Error:
        dialeto = csv.excel
        dialeto.delimiter = ";"
    leitor = csv.DictReader(texto.splitlines(), dialect=dialeto)
    if not leitor.fieldnames:
        raise ValueError(f"{caminho.name}: arquivo sem cabeçalho")

    colunas: dict[str, str] = {}
    for nome in leitor.fieldnames:
        chave = normalizar(nome)
        for campo, sinonimos in ALIASES.items():
            if chave in sinonimos and campo not in colunas:
                colunas[campo] = nome
    if mapa_colunas:
        colunas.update(mapa_colunas)

    if "data" not in colunas or "historico" not in colunas:
        raise ValueError(
            f"{caminho.name}: não encontrei colunas de data e histórico. "
            f"Cabeçalho lido: {leitor.fieldnames}"
        )
    if "valor" not in colunas and not ("entrada" in colunas or "saida" in colunas):
        raise ValueError(f"{caminho.name}: não encontrei coluna de valor")

    transacoes: list[Transacao] = []
    for numero, linha in enumerate(leitor, start=2):  # linha 1 é o cabeçalho
        if not any((v or "").strip() for v in linha.values()):
            continue
        bruto_data = (linha.get(colunas["data"]) or "").strip()
        historico = (linha.get(colunas["historico"]) or "").strip()
        # Linhas de saldo não são movimentação.
        if normalizar(historico).startswith(("SALDO", "S A L D O")):
            continue
        if "valor" in colunas and (linha.get(colunas["valor"]) or "").strip():
            valor = para_decimal(linha[colunas["valor"]])
        else:
            entrada = (linha.get(colunas.get("entrada", ""), "") or "").strip()
            saida = (linha.get(colunas.get("saida", ""), "") or "").strip()
            if entrada:
                valor = abs(para_decimal(entrada))
            elif saida:
                valor = -abs(para_decimal(saida))
            else:
                raise ValueError(f"{caminho.name}, linha {numero}: sem valor")
        transacoes.append(
            Transacao(
                conta_bancaria=conta_bancaria,
                data=_data(bruto_data),
                valor=valor,
                historico=historico,
                documento=(linha.get(colunas.get("documento", ""), "") or "").strip()
                or None,
                fitid=(linha.get(colunas.get("id", ""), "") or "").strip() or None,
                origem=caminho.name,
                linha=numero,
            )
        )
    return transacoes
