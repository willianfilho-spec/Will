"""Avaliação com planilhas reais, fora do repositório.

    MOTOR_PLANILHAS_REAIS=/caminho/da/pasta pytest testes/test_dados_reais.py

Sem a variável, o teste é ignorado. Verifica as garantias que não podem
falhar em nenhum mês; os números detalhados saem em
ferramentas/avaliar_planilhas.py.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

PASTA = os.environ.get("MOTOR_PLANILHAS_REAIS")
pytestmark = pytest.mark.skipif(not PASTA, reason="defina MOTOR_PLANILHAS_REAIS para usar dados reais")
EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"


def arquivos():
    return sorted(Path(PASTA).glob("*.xlsx")) if PASTA else []


@pytest.mark.parametrize("arquivo", arquivos(), ids=lambda p: p.name)
def test_garantias_com_planilha_real(arquivo, tmp_path):
    from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas, Status
    from motor_contabil.leitores.planilha_despesas import ler_planilha_despesas
    from motor_contabil.texto import normalizar

    motor = Motor(BancoDeDados(tmp_path / "real.db"), PlanoDeContas.carregar(EXEMPLOS / "plano_contas.csv"),
                  ConjuntoDeRegras.carregar(EXEMPLOS / "regras.json"))
    lidas = ler_planilha_despesas(arquivo, "BANCO")
    r1 = motor.importar(arquivo, "BANCO")
    r2 = motor.importar(arquivo, "BANCO")
    itens = motor.listar()

    assert r1.novas == len(lidas)                                     # nada perdido
    assert r2.novas == 0                                              # nada duplicado
    assert sum(Decimal(i["valor"]) for i in itens) == sum(t.valor for t in lidas)
    for i in itens:                                                   # PIX nunca sai sozinho
        if normalizar(i["historico_banco"]).startswith("PIX"):
            assert i["status"] != Status.LIBERADO.value
    motor.banco.fechar()
