"""Etapa 1: leitura do extrato (CSV ou XLSX) e conversão para objetos Transacao."""

import csv
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .modelos import Extrato, Transacao


class ErroExtrato(Exception):
    """Problema no arquivo de extrato que impede uma leitura confiável."""


# Nomes de coluna aceitos (já normalizados: minúsculos e sem acento).
COLUNAS_DATA = {"data", "data lancamento", "data movimento", "data mov", "dt"}
COLUNAS_DESCRICAO = {"descricao", "historico", "lancamento", "detalhe", "detalhes", "memo"}
COLUNAS_VALOR = {"valor", "valor (r$)", "valor r$", "montante"}
COLUNAS_DEBITO = {"debito", "debito (r$)", "saida", "saidas"}
COLUNAS_CREDITO = {"credito", "credito (r$)", "entrada", "entradas"}
COLUNAS_TIPO = {"tipo", "d/c", "dc", "natureza"}
COLUNAS_DOCUMENTO = {"documento", "doc", "numero", "n documento", "nr documento", "id"}

FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S")
LINHAS_ATE_CABECALHO = 30  # extratos de banco costumam ter título antes da tabela


def normalizar(texto) -> str:
    """Minúsculas, sem acentos e sem espaços duplicados."""
    sem_acento = unicodedata.normalize("NFKD", "" if texto is None else str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def converter_valor(bruto) -> Decimal:
    """Converte '1.234,56', '-1234.56', 'R$ 100,00', '(50,00)', '50,00 D' ou número em Decimal."""
    if isinstance(bruto, bool):
        raise ValueError(f"valor não reconhecido: {bruto!r}")
    if isinstance(bruto, (int, float, Decimal)):  # célula numérica de planilha
        return Decimal(str(bruto)).quantize(Decimal("0.01"))

    texto = ("" if bruto is None else str(bruto)).strip().upper()
    if not texto:
        raise ValueError("valor vazio")

    negativo = False
    if texto.startswith("(") and texto.endswith(")"):
        negativo, texto = True, texto[1:-1]
    if texto.endswith("D"):
        negativo, texto = True, texto[:-1]
    elif texto.endswith("C"):
        texto = texto[:-1]
    if "-" in texto:
        negativo, texto = True, texto.replace("-", "")

    numero = re.sub(r"[R$\s+]", "", texto)
    if not re.fullmatch(r"[\d.,]+", numero):
        raise ValueError(f"valor não reconhecido: {bruto!r}")

    if "," in numero and "." in numero:
        # O separador que aparece por último é o decimal.
        if numero.rfind(",") > numero.rfind("."):
            numero = numero.replace(".", "").replace(",", ".")
        else:
            numero = numero.replace(",", "")
    elif "," in numero:
        numero = numero.replace(",", ".")
    elif numero.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", numero):
        # Só pontos: '1.234' ou '1.234.567' são milhares no padrão brasileiro.
        numero = numero.replace(".", "")

    try:
        valor = Decimal(numero)
    except InvalidOperation as erro:
        raise ValueError(f"valor não reconhecido: {bruto!r}") from erro
    return -valor if negativo else valor


def converter_data(bruto) -> date:
    if isinstance(bruto, datetime):  # célula de data de planilha
        return bruto.date()
    if isinstance(bruto, date):
        return bruto
    limpo = ("" if bruto is None else str(bruto)).strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(limpo, formato).date()
        except ValueError:
            continue
    raise ValueError(f"data não reconhecida: {bruto!r}")


def ler_texto(caminho: Path) -> str:
    """Bancos e o Excel gravam ora em UTF-8, ora em Latin-1 (Windows)."""
    dados = Path(caminho).read_bytes()
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise ErroExtrato(f"Não foi possível decodificar {caminho}")


def detectar_delimitador(amostra: str) -> str:
    return max(";,\t|", key=amostra.count)


def _linhas_csv(caminho: Path) -> list[tuple[int, list]]:
    linhas = ler_texto(caminho).splitlines()
    delimitador = detectar_delimitador("\n".join(linhas[:LINHAS_ATE_CABECALHO]))
    return [
        (numero, next(csv.reader([linha], delimiter=delimitador)))
        for numero, linha in enumerate(linhas, start=1)
        if linha.strip()
    ]


def _linhas_xlsx(caminho: Path) -> list[tuple[int, list]]:
    try:
        import openpyxl
    except ImportError as erro:
        raise ErroExtrato("Para ler XLSX instale:  pip install openpyxl") from erro
    planilha = openpyxl.load_workbook(caminho, read_only=True, data_only=True).worksheets[0]
    return [
        (numero, list(linha))
        for numero, linha in enumerate(planilha.iter_rows(values_only=True), start=1)
        if any(celula is not None and str(celula).strip() for celula in linha)
    ]


def _mapear_colunas(celulas: list) -> dict | None:
    """Devolve {papel: índice} se a linha for um cabeçalho válido; senão None."""
    nomes = {normalizar(c): i for i, c in enumerate(celulas) if c is not None and normalizar(c)}

    def achar(aceitas):
        return next((i for nome, i in nomes.items() if nome in aceitas), None)

    mapa = {
        "data": achar(COLUNAS_DATA), "descricao": achar(COLUNAS_DESCRICAO),
        "valor": achar(COLUNAS_VALOR), "debito": achar(COLUNAS_DEBITO),
        "credito": achar(COLUNAS_CREDITO), "tipo": achar(COLUNAS_TIPO),
        "documento": achar(COLUNAS_DOCUMENTO),
    }
    tem_valor = mapa["valor"] is not None or (mapa["debito"] is not None and mapa["credito"] is not None)
    if mapa["data"] is None or mapa["descricao"] is None or not tem_valor:
        return None
    return mapa


def _opcional(celula) -> Decimal | None:
    """Célula de débito/crédito: vazia, '-' ou zero contam como 'sem valor'."""
    if celula is None or str(celula).strip() in ("", "-"):
        return None
    valor = converter_valor(celula)
    return None if valor == 0 else valor


def ler_extrato(caminho) -> Extrato:
    """Lê o arquivo e devolve os movimentos e os saldos informados nele.

    Qualquer linha que não possa ser interpretada interrompe a leitura com a
    lista completa dos problemas: em contabilidade, pular linha em silêncio é
    pior do que parar.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroExtrato(f"Arquivo não encontrado: {caminho}")
    extensao = caminho.suffix.lower()
    if extensao in (".xlsx", ".xlsm"):
        linhas = _linhas_xlsx(caminho)
    elif extensao in (".csv", ".txt"):
        linhas = _linhas_csv(caminho)
    else:
        raise ErroExtrato(f"Formato não suportado: {extensao or caminho.name}. Use CSV ou XLSX.")

    mapa, inicio = None, 0
    for posicao, (_, celulas) in enumerate(linhas[:LINHAS_ATE_CABECALHO]):
        mapa = _mapear_colunas(celulas)
        if mapa:
            inicio = posicao + 1
            break
    if not mapa:
        raise ErroExtrato(
            "Cabeçalho não encontrado. O arquivo precisa de uma linha com as colunas "
            "data, descrição (ou histórico) e valor (ou débito + crédito)."
        )

    def celula(celulas, papel):
        indice = mapa[papel]
        return celulas[indice] if indice is not None and indice < len(celulas) else None

    extrato, erros = Extrato(), []
    for numero, celulas in linhas[inicio:]:
        descricao = re.sub(r"\s+", " ", str(celula(celulas, "descricao") or "")).strip()
        try:
            if mapa["valor"] is not None:
                valor = converter_valor(celula(celulas, "valor"))
                tipo = normalizar(celula(celulas, "tipo"))[:1]
                if tipo == "d":
                    valor = -abs(valor)
                elif tipo == "c":
                    valor = abs(valor)
            else:
                debito, credito = _opcional(celula(celulas, "debito")), _opcional(celula(celulas, "credito"))
                if (debito is None) == (credito is None):
                    raise ValueError("preencha débito ou crédito (apenas um)")
                valor = abs(credito) if credito is not None else -abs(debito)
        except ValueError as erro:
            valor, erro_valor = None, erro
        else:
            erro_valor = None

        if normalizar(descricao).startswith("saldo"):
            # Linha informativa: não é movimento, mas serve para conferir o total.
            extrato.linhas_saldo += 1
            rotulo = normalizar(descricao)
            if valor is not None:
                if ("anterior" in rotulo or "inicial" in rotulo) and extrato.saldo_inicial is None:
                    extrato.saldo_inicial = valor
                elif "final" in rotulo or "atual" in rotulo:
                    extrato.saldo_final = valor
            continue

        try:
            if erro_valor:
                raise erro_valor
            data = converter_data(celula(celulas, "data"))
            if valor == 0:
                raise ValueError("valor zero")
            if not descricao:
                raise ValueError("descrição vazia")
        except ValueError as erro:
            erros.append(f"  linha {numero}: {erro}")
            continue
        documento = str(celula(celulas, "documento") or "").strip()
        extrato.transacoes.append(Transacao(numero, data, descricao, valor, documento))

    if erros:
        raise ErroExtrato("Linhas inválidas no extrato:\n" + "\n".join(erros))
    if not extrato.transacoes:
        raise ErroExtrato("Nenhum movimento encontrado no extrato.")
    return extrato
