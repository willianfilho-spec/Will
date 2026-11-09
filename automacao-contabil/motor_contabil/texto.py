"""Funções de texto e números no formato brasileiro."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acentos e com espaços simples. Usado em regras e chaves."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


def para_decimal(bruto: str) -> Decimal:
    """Converte '1.200,50', '-45,00', '1200.50' ou '(45,00)' em Decimal.

    Regra: se houver vírgula, ela é o separador decimal e pontos são milhares.
    Sem vírgula, o ponto é decimal (formato OFX e planilhas exportadas em inglês).
    """
    s = (bruto or "").strip().replace("R$", "").replace(" ", "")
    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo, s = True, s[1:-1]
    if s.endswith("-"):  # alguns bancos escrevem 45,00-
        negativo, s = True, s[:-1]
    if s.upper().endswith("D"):  # e outros 45,00 D / 45,00 C
        negativo, s = True, s[:-1]
    elif s.upper().endswith("C"):
        s = s[:-1]
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(s)
    except InvalidOperation as erro:
        raise ValueError(f"valor monetário inválido: {bruto!r}") from erro
    if not valor.is_finite():
        raise ValueError("informe um valor monetário finito")
    if valor.as_tuple().exponent < -2 and valor != valor.quantize(Decimal("0.01")):
        raise ValueError("valor com fração de centavo; confira o extrato")
    return -valor if negativo else valor


def formatar_valor(valor: Decimal) -> str:
    """Decimal -> '1200,50' (sem separador de milhar, como a maioria dos leiautes pede)."""
    return f"{abs(valor):.2f}".replace(".", ",")


_CPF_CNPJ = re.compile(
    r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"            # CPF
    r"|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"     # CNPJ
)


def mascarar_documentos(texto: str) -> str:
    """Remove CPF/CNPJ antes de enviar um histórico a um serviço externo."""
    return _CPF_CNPJ.sub("[DOC]", texto or "")
