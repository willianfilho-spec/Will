"""Conversão segura entre texto, Decimal e centavos (INTEGER).

Regra do projeto: valor persistido é sempre inteiro em centavos; contas são
feitas em Decimal. Fração de centavo é recusada, nunca arredondada em silêncio.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CEM = Decimal(100)


class ValorInvalido(ValueError):
    pass


def para_decimal(valor) -> Decimal:
    """Aceita int, Decimal, float finito ou texto nos formatos BR e internacional.

    Exemplos aceitos: "1.234,56", "1234,56", "1234.56", "-1.234,56",
    "(1.234,56)", "R$ 1.234,56", "1.234,56-", "1,234.56".
    """
    if isinstance(valor, bool):
        raise ValorInvalido("valor booleano não é monetário")
    if isinstance(valor, Decimal):
        d = valor
    elif isinstance(valor, int):
        d = Decimal(valor)
    elif isinstance(valor, float):
        if valor != valor or valor in (float("inf"), float("-inf")):
            raise ValorInvalido("valor não finito")
        d = Decimal(repr(valor))
    elif isinstance(valor, str):
        d = _texto_para_decimal(valor)
    else:
        raise ValorInvalido(f"tipo não suportado: {type(valor).__name__}")
    if not d.is_finite():
        raise ValorInvalido("valor não finito")
    return d


def _texto_para_decimal(texto: str) -> Decimal:
    t = texto.strip().replace(" ", "").replace(" ", "")
    if not t:
        raise ValorInvalido("valor vazio")
    negativo = False
    if t.startswith("(") and t.endswith(")"):
        negativo, t = True, t[1:-1]
    if t.endswith("-"):
        negativo, t = True, t[:-1]
    t = re.sub(r"^R\$", "", t, flags=re.I)
    if t.startswith("-"):
        negativo, t = True, t[1:]
    elif t.startswith("+"):
        t = t[1:]
    if not re.fullmatch(r"[\d.,]+", t):
        raise ValorInvalido(f"valor com caracteres inválidos: {texto!r}")
    if "," in t and "." in t:
        # o último separador é o decimal
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        if t.count(",") > 1:
            raise ValorInvalido(f"valor ambíguo: {texto!r}")
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")  # 1.234.567 = milhar
    elif "." in t and len(t.split(".")[1]) == 3 and len(t.split(".")[0]) <= 3 and t.split(".")[0] != "0":
        # "1.234" é ambíguo (mil duzentos e trinta e quatro ou 1,234); recusar.
        raise ValorInvalido(f"valor ambíguo (milhar ou decimal?): {texto!r}")
    try:
        d = Decimal(t)
    except InvalidOperation as exc:
        raise ValorInvalido(f"valor inválido: {texto!r}") from exc
    return -d if negativo else d


def para_centavos(valor) -> int:
    d = para_decimal(valor) * CEM
    if d != d.to_integral_value():
        raise ValorInvalido(f"valor com fração de centavo: {valor!r}")
    return int(d)


def de_centavos(centavos: int) -> Decimal:
    if not isinstance(centavos, int) or isinstance(centavos, bool):
        raise ValorInvalido("centavos deve ser inteiro")
    return Decimal(centavos) / CEM


def formatar_br(centavos: int, simbolo: bool = True) -> str:
    """12345 -> 'R$ 123,45'; -100000 -> '-R$ 1.000,00'."""
    sinal = "-" if centavos < 0 else ""
    inteiro, cent = divmod(abs(centavos), 100)
    corpo = f"{inteiro:,}".replace(",", ".") + f",{cent:02d}"
    return f"{sinal}{'R$ ' if simbolo else ''}{corpo}"


def formatar_fortes(centavos: int) -> str:
    """Leiaute do Fortes: positivo, vírgula decimal, sem milhar. 123456 -> '1234,56'."""
    if centavos <= 0:
        raise ValorInvalido("o Fortes recebe só valor positivo")
    inteiro, cent = divmod(centavos, 100)
    return f"{inteiro},{cent:02d}"
