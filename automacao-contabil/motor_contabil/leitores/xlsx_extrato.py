"""Leitor de planilhas Excel (.xlsx) de movimentação bancária.

Feito a partir das planilhas mensais que os clientes já enviam ao escritório:
um título, uma linha de cabeçalho (DATA, LANÇAMENTO BANCÁRIO, DESCRIÇÃO,
VALOR, CAIXA/BANCO), uma linha por movimento e, às vezes, uma linha de total
sem data no fim.

- O cabeçalho é procurado nas primeiras 30 linhas: é a primeira que tem
  coluna de data e de valor.
- O histórico junta, na ordem das colunas, todo texto da linha que não seja
  data, valor, documento, identificador ou caixa/banco. Assim "PIX ENVIADO" +
  "FULANO DE TAL" vira "PIX ENVIADO FULANO DE TAL", mesmo quando a coluna do
  favorecido não tem nome.
- Se acima do cabeçalho houver o título DESPESAS (ou SAIDAS), os valores são
  saídas; com RECEITAS (ou ENTRADAS), são entradas. Sem título, vale o sinal
  do próprio valor (negativo = saída).
- Linha com data e valor, mas sem nenhum texto, entra com o histórico
  "SEM HISTORICO NA PLANILHA": nenhuma regra a reconhece e ela vai para revisão.
- Linha sem data só com números (total ou subtotal) é ignorada. Linha sem data
  com texto é erro: pode ser um movimento com a data apagada.

Usa só a biblioteca padrão. O valor é lido como o texto gravado no arquivo,
não como número de ponto flutuante, para não perder centavos.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from ..modelo import Transacao
from ..texto import normalizar, para_decimal
from .csv_extrato import ALIASES, _data

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
ALIASES_XLSX = {
    **ALIASES,
    "historico": ALIASES["historico"] | {"LANCAMENTO BANCARIO", "FAVORECIDO"},
    "caixa_banco": {"CAIXA/BANCO", "CAIXA / BANCO", "CONTA", "BANCO"},
}
CAMPOS_FORA_DO_HISTORICO = {"data", "valor", "entrada", "saida", "documento", "id", "caixa_banco"}
TITULOS_SAIDA = {"DESPESAS", "SAIDAS", "PAGAMENTOS"}
TITULOS_ENTRADA = {"RECEITAS", "ENTRADAS", "RECEBIMENTOS"}
EPOCA_EXCEL = date(1899, 12, 30)
SEM_HISTORICO = "SEM HISTORICO NA PLANILHA"


def _coluna(referencia: str) -> int:
    letras = re.match(r"[A-Z]+", referencia).group(0)
    numero = 0
    for letra in letras:
        numero = numero * 26 + ord(letra) - 64
    return numero - 1


def _celulas(xml: bytes, compartilhadas: list[str]) -> list[list[str | None]]:
    linhas: list[list[str | None]] = []
    for linha in ET.fromstring(xml).iterfind(".//m:sheetData/m:row", NS):
        numero = int(linha.get("r", len(linhas) + 1))
        while len(linhas) < numero:
            linhas.append([])
        valores: list[str | None] = []
        for celula in linha.iterfind("m:c", NS):
            indice = _coluna(celula.get("r")) if celula.get("r") else len(valores)
            tipo = celula.get("t")
            if tipo == "inlineStr":
                texto = "".join(t.text or "" for t in celula.iterfind(".//m:t", NS))
            else:
                v = celula.find("m:v", NS)
                texto = v.text if v is not None else None
                if texto is not None and tipo == "s":
                    texto = compartilhadas[int(texto)]
            while len(valores) <= indice:
                valores.append(None)
            valores[indice] = texto
        linhas[numero - 1] = valores
    return linhas


def _primeira_planilha(caminho: Path) -> tuple[str, list[list[str | None]]]:
    try:
        arquivo = zipfile.ZipFile(caminho)
    except zipfile.BadZipFile as erro:
        raise ValueError(f"{caminho.name}: não é um arquivo .xlsx válido") from erro
    with arquivo:
        nomes = set(arquivo.namelist())
        compartilhadas: list[str] = []
        if "xl/sharedStrings.xml" in nomes:
            for item in ET.fromstring(arquivo.read("xl/sharedStrings.xml")).iterfind("m:si", NS):
                compartilhadas.append("".join(t.text or "" for t in item.iterfind(".//m:t", NS)))
        livro = ET.fromstring(arquivo.read("xl/workbook.xml"))
        planilhas = livro.findall("m:sheets/m:sheet", NS)
        if not planilhas:
            raise ValueError(f"{caminho.name}: a pasta de trabalho não tem planilhas")
        if len(planilhas) > 1:
            raise ValueError(
                f"{caminho.name}: tem {len(planilhas)} planilhas. Envie um arquivo com uma "
                "única planilha de movimentação, para não misturar meses ou contas."
            )
        rels = ET.fromstring(arquivo.read("xl/_rels/workbook.xml.rels"))
        alvos = {r.get("Id"): r.get("Target") for r in rels}
        alvo = alvos[planilhas[0].get(REL)]
        caminho_planilha = alvo.lstrip("/") if alvo.startswith("/") else str(
            PurePosixPath("xl") / alvo
        )
        return planilhas[0].get("name", ""), _celulas(arquivo.read(caminho_planilha), compartilhadas)


def _data_xlsx(bruto: str) -> date:
    try:
        serial = float(bruto)
    except ValueError:
        return _data(bruto)
    if not 1 <= serial < 2958466:
        raise ValueError(f"data inválida: {bruto!r}")
    return EPOCA_EXCEL + timedelta(days=int(serial))


def _valor_xlsx(bruto: str) -> Decimal:
    """O Excel grava 2312.81 às vezes como 2312.8099999999999: aceita só ruído de arredondamento."""
    texto = bruto.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?([eE]-?\d+)?", texto):
        try:
            exato = Decimal(texto)
        except InvalidOperation as erro:
            raise ValueError(f"valor monetário inválido: {bruto!r}") from erro
        centavos = exato.quantize(Decimal("0.01"))
        if abs(exato - centavos) > Decimal("0.000001"):
            raise ValueError("valor com fração de centavo; confira a planilha")
        return centavos
    return para_decimal(texto)


def ler_xlsx(caminho: str | Path, conta_bancaria: str) -> list[Transacao]:
    caminho = Path(caminho)
    _, linhas = _primeira_planilha(caminho)

    cabecalho = None
    for numero, linha in enumerate(linhas[:30]):
        nomes = {normalizar(v): i for i, v in enumerate(linha) if v and v.strip()}
        if any(n in ALIASES_XLSX["data"] for n in nomes) and any(
            n in ALIASES_XLSX["valor"] | ALIASES_XLSX["entrada"] | ALIASES_XLSX["saida"] for n in nomes
        ):
            cabecalho = numero
            break
    if cabecalho is None:
        raise ValueError(f"{caminho.name}: não encontrei a linha de cabeçalho com DATA e VALOR")

    colunas: dict[str, int] = {}
    for indice, nome in enumerate(linhas[cabecalho]):
        chave = normalizar(nome or "")
        for campo, sinonimos in ALIASES_XLSX.items():
            if chave in sinonimos and campo not in colunas:
                colunas[campo] = indice

    titulos = {normalizar(v) for linha in linhas[:cabecalho] for v in linha if v}
    sentido_fixo = None
    if titulos & TITULOS_SAIDA:
        sentido_fixo = "saida"
    elif titulos & TITULOS_ENTRADA:
        sentido_fixo = "entrada"

    fora = {colunas[c] for c in CAMPOS_FORA_DO_HISTORICO if c in colunas}
    transacoes: list[Transacao] = []
    for numero, linha in enumerate(linhas[cabecalho + 1:], start=cabecalho + 2):
        def valor_de(campo: str) -> str:
            i = colunas.get(campo)
            return (linha[i] or "").strip() if i is not None and i < len(linha) else ""

        if not any((v or "").strip() for v in linha):
            continue
        bruto_data = valor_de("data")
        textos = [
            (v or "").strip() for i, v in enumerate(linha)
            if i not in fora and v and v.strip() and not re.fullmatch(r"-?[\d.,]+([eE]-?\d+)?", v.strip())
        ]
        if not bruto_data:
            if textos:
                raise ValueError(
                    f"{caminho.name}, linha {numero}: movimento sem data ({' '.join(textos)[:60]})"
                )
            continue  # total ou subtotal
        if valor_de("caixa_banco"):
            raise ValueError(
                f"{caminho.name}, linha {numero}: a coluna CAIXA/BANCO está preenchida. Separe a "
                "planilha por conta e informe a conta bancária ao importar."
            )
        # Movimento real sem descrição: entra para revisão, nunca é descartado.
        historico = " ".join(textos) or SEM_HISTORICO
        if valor_de("valor"):
            valor = _valor_xlsx(valor_de("valor"))
        elif valor_de("entrada"):
            valor = abs(_valor_xlsx(valor_de("entrada")))
        elif valor_de("saida"):
            valor = -abs(_valor_xlsx(valor_de("saida")))
        else:
            raise ValueError(f"{caminho.name}, linha {numero}: sem valor")
        if sentido_fixo:
            if valor < 0:
                raise ValueError(
                    f"{caminho.name}, linha {numero}: valor negativo numa planilha de "
                    f"{'despesas' if sentido_fixo == 'saida' else 'receitas'}; confira o sinal"
                )
            valor = -valor if sentido_fixo == "saida" else valor
        transacoes.append(
            Transacao(
                conta_bancaria=conta_bancaria,
                data=_data_xlsx(bruto_data),
                valor=valor,
                historico=historico,
                documento=valor_de("documento") or None,
                fitid=valor_de("id") or None,
                origem=caminho.name,
                linha=numero,
            )
        )
    if not transacoes:
        raise ValueError(f"{caminho.name}: nenhum movimento encontrado abaixo do cabeçalho")
    return transacoes
