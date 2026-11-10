"""Etapa 1: leitura do extrato em CSV e conversão para objetos Transacao."""

import csv
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .modelos import Transacao


class ErroExtrato(Exception):
    """Problema no arquivo de extrato que impede uma leitura confiável."""


# Nomes de coluna aceitos (já normalizados: minúsculos e sem acento).
COLUNAS_DATA = {"data", "data lancamento", "data movimento", "dt"}
COLUNAS_DESCRICAO = {"descricao", "historico", "lancamento", "detalhe", "memo"}
COLUNAS_VALOR = {"valor", "valor (r$)", "valor r$", "montante"}
COLUNAS_DEBITO = {"debito", "saida", "saidas"}
COLUNAS_CREDITO = {"credito", "entrada", "entradas"}
COLUNAS_TIPO = {"tipo", "d/c", "dc", "natureza"}
COLUNAS_DOCUMENTO = {"documento", "doc", "numero", "n documento", "id"}

FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem espaços duplicados."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def converter_valor(texto: str) -> Decimal:
    """Converte '1.234,56', '-1234.56', 'R$ 100,00', '(50,00)' ou '50,00 D' em Decimal."""
    bruto = (texto or "").strip().upper()
    if not bruto:
        raise ValueError("valor vazio")

    negativo = False
    if bruto.startswith("(") and bruto.endswith(")"):
        negativo, bruto = True, bruto[1:-1]
    if bruto.endswith("D"):
        negativo, bruto = True, bruto[:-1]
    elif bruto.endswith("C"):
        bruto = bruto[:-1]
    if "-" in bruto:
        negativo, bruto = True, bruto.replace("-", "")

    numero = re.sub(r"[R$\s+]", "", bruto)
    if not re.fullmatch(r"[\d.,]+", numero):
        raise ValueError(f"valor não reconhecido: {texto!r}")

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
        raise ValueError(f"valor não reconhecido: {texto!r}") from erro
    return -valor if negativo else valor


def converter_data(texto: str) -> date:
    limpo = (texto or "").strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(limpo, formato).date()
        except ValueError:
            continue
    raise ValueError(f"data não reconhecida: {texto!r}")


def _ler_texto(caminho: Path) -> str:
    """Bancos brasileiros exportam ora em UTF-8, ora em Latin-1 (Windows)."""
    dados = caminho.read_bytes()
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise ErroExtrato(f"Não foi possível decodificar {caminho}")


def _detectar_delimitador(cabecalho: str) -> str:
    return max(";,\t|", key=cabecalho.count)


def _achar(colunas: dict, aceitas: set):
    for nome_normalizado, nome_original in colunas.items():
        if nome_normalizado in aceitas:
            return nome_original
    return None


def ler_extrato(caminho) -> tuple[list[Transacao], int]:
    """Lê o CSV e devolve (transações, quantidade de linhas de saldo ignoradas).

    Qualquer linha que não possa ser interpretada interrompe a leitura com a
    lista completa dos problemas: em contabilidade, pular linha em silêncio é
    pior do que parar.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroExtrato(f"Arquivo não encontrado: {caminho}")

    linhas = [l for l in _ler_texto(caminho).splitlines() if l.strip()]
    if len(linhas) < 2:
        raise ErroExtrato("O extrato precisa de um cabeçalho e ao menos uma linha.")

    leitor = csv.DictReader(linhas, delimiter=_detectar_delimitador(linhas[0]))
    colunas = {normalizar(nome): nome for nome in (leitor.fieldnames or []) if nome}

    col_data = _achar(colunas, COLUNAS_DATA)
    col_desc = _achar(colunas, COLUNAS_DESCRICAO)
    col_valor = _achar(colunas, COLUNAS_VALOR)
    col_deb = _achar(colunas, COLUNAS_DEBITO)
    col_cred = _achar(colunas, COLUNAS_CREDITO)
    col_tipo = _achar(colunas, COLUNAS_TIPO)
    col_doc = _achar(colunas, COLUNAS_DOCUMENTO)

    if not col_data or not col_desc or not (col_valor or (col_deb and col_cred)):
        raise ErroExtrato(
            "Colunas obrigatórias não encontradas. Esperado: data, descrição e "
            "valor (ou débito + crédito). Encontrado: "
            + ", ".join(leitor.fieldnames or [])
        )

    transacoes, erros, saldos_ignorados = [], [], 0
    for numero, registro in enumerate(leitor, start=2):
        descricao = re.sub(r"\s+", " ", registro.get(col_desc) or "").strip()
        if normalizar(descricao).startswith("saldo"):
            saldos_ignorados += 1  # linha informativa, não é movimento
            continue
        try:
            data = converter_data(registro.get(col_data))
            if col_valor:
                valor = converter_valor(registro.get(col_valor))
                tipo = normalizar(registro.get(col_tipo) or "") if col_tipo else ""
                if tipo[:1] == "d":
                    valor = -abs(valor)
                elif tipo[:1] == "c":
                    valor = abs(valor)
            else:
                debito = (registro.get(col_deb) or "").strip()
                credito = (registro.get(col_cred) or "").strip()
                if bool(debito) == bool(credito):
                    raise ValueError("preencha débito ou crédito (apenas um)")
                valor = abs(converter_valor(credito)) if credito else -abs(converter_valor(debito))
            if valor == 0:
                raise ValueError("valor zero")
            if not descricao:
                raise ValueError("descrição vazia")
        except ValueError as erro:
            erros.append(f"  linha {numero}: {erro}")
            continue
        documento = (registro.get(col_doc) or "").strip() if col_doc else ""
        transacoes.append(Transacao(numero, data, descricao, valor, documento))

    if erros:
        raise ErroExtrato("Linhas inválidas no extrato:\n" + "\n".join(erros))
    if not transacoes:
        raise ErroExtrato("Nenhum movimento encontrado no extrato.")
    return transacoes, saldos_ignorados
