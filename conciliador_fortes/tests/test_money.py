from decimal import Decimal

import pytest

from domain.money import ValorInvalido, de_centavos, formatar_br, formatar_fortes, para_centavos


@pytest.mark.parametrize("entrada, esperado", [
    ("1.234,56", 123456), ("1234,56", 123456), ("1234.56", 123456), ("-1.234,56", -123456),
    ("(1.234,56)", -123456), ("R$ 1.234,56", 123456), ("1.234,56-", -123456), ("1,234.56", 123456),
    ("0,01", 1), ("-45.90", -4590), ("1.234.567", 123456700), (Decimal("10.5"), 1050), (12, 1200), (0.1, 10),
])
def test_conversao(entrada, esperado):
    assert para_centavos(entrada) == esperado


@pytest.mark.parametrize("entrada", ["1,234", "abc", "", "1.234", "0,001", float("nan"), "1,2,3", True])
def test_recusa(entrada):
    with pytest.raises(ValorInvalido):
        para_centavos(entrada)


def test_formatos():
    assert formatar_br(123456789) == "R$ 1.234.567,89"
    assert formatar_br(-5) == "-R$ 0,05"
    assert formatar_fortes(123456789) == "1234567,89"
    assert de_centavos(1) == Decimal("0.01")
    with pytest.raises(ValorInvalido):
        formatar_fortes(0)
