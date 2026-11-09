"""Testes do leitor de planilhas "Despesas extrato" e dos problemas
encontrados ao rodar o motor sobre as planilhas reais (maio a outubro/2026).

Todos os dados aqui são fictícios; as planilhas reais nunca entram no
repositório. Para rodar a avaliação com elas, ver test_dados_reais.py.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas  # noqa: E402
from motor_contabil.idempotencia import calcular_chaves  # noqa: E402
from motor_contabil.leitores import ler_csv, ler_extrato  # noqa: E402
from motor_contabil.leitores.planilha_despesas import (  # noqa: E402
    ALERTA_DOIS_NOMES, ALERTA_ENCARGO_COM_FAVORECIDO, ALERTA_SEM_TIPO, ler_planilha_despesas)

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"
CONTA = "001-0001-00000-0"


def planilha(caminho: Path, linhas: list[tuple], com_total: bool = True) -> Path:
    """Reproduz o leiaute das planilhas reais, com dados fictícios."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Agosto 2026"
    ws.append([None, "EMPRESA: EMPRESA FICTÍCIA LTDA   ", None, None, None])
    ws.append(["DESPESAS", None, None, None, None])
    ws.append(["DATA", "LANÇAMENTO BANCÁRIO ", "DESCRIÇÃO ", "VALOR", "CAIXA/BANCO"])
    for dia, lanc, desc, valor in linhas:
        ws.append([datetime(2026, 8, dia), lanc, desc, valor, None])
    if com_total:
        ws.append([None, None, None, f"=SUM(D4:D{3 + len(linhas)})", None])
    wb.save(caminho)
    return caminho


@pytest.fixture
def motor(tmp_path):
    m = Motor(BancoDeDados(tmp_path / "t.db"), PlanoDeContas.carregar(EXEMPLOS / "plano_contas.csv"),
              ConjuntoDeRegras.carregar(EXEMPLOS / "regras.json"))
    yield m
    m.banco.fechar()


# ------------------------------------------------------------------ leitura
def test_le_formato_ignora_total_e_preserva_centavos(tmp_path):
    arq = planilha(tmp_path / "p.xlsx", [
        (3, "BOLETO PAGO FORNECEDOR EXEMPLO", None, 9876.5),
        (3, "PIX ENVIADO", "MARIA EXEMPLO", 0.1),
        (4, "PIX ENVIADO", "JOAO EXEMPLO", 0.2),
        (5, "TAR PLANO ADAPT 1 07/26", None, 150),
    ])
    ts = ler_planilha_despesas(arq, CONTA)
    assert len(ts) == 4  # a linha =SUM não é movimentação
    assert [t.valor for t in ts] == [Decimal("-9876.50"), Decimal("-0.10"), Decimal("-0.20"), Decimal("-150.00")]
    # 0.1 + 0.2 em ponto flutuante dá 0.30000000000000004; em Decimal, 0.30
    assert sum(t.valor for t in ts[1:3]) == Decimal("-0.30")
    assert ts[1].historico == "PIX ENVIADO" and ts[1].favorecido == "MARIA EXEMPLO"
    assert ts[0].favorecido is None
    assert ts[0].conta_bancaria == CONTA and ts[0].linha == 4
    assert ler_extrato(arq, CONTA) == ts


def test_exige_conta_bancaria(tmp_path):
    arq = planilha(tmp_path / "p.xlsx", [(3, "IOF", None, 1.5)])
    with pytest.raises(ValueError, match="conta bancária"):
        ler_extrato(arq)


def test_recusa_valor_com_mais_de_duas_casas(tmp_path):
    arq = planilha(tmp_path / "p.xlsx", [(3, "PIX ENVIADO", "X", 10.005)])
    with pytest.raises(ValueError, match="duas casas"):
        ler_planilha_despesas(arq, CONTA)


def test_recusa_planilha_sem_cabecalho(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.append(["qualquer", "coisa"])
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(ValueError, match="cabeçalho"):
        ler_planilha_despesas(tmp_path / "x.xlsx", CONTA)


# ------------------------------------------------------------------ duplicidade
def test_pix_iguais_para_favorecidos_diferentes_nao_sao_duplicidade(motor, tmp_path):
    # Caso real: 12 PIX de R$ 500,00 no mesmo dia, todos "PIX ENVIADO".
    linhas = [(25, "PIX ENVIADO", f"FAVORECIDO {i}", 500) for i in range(12)]
    motor.importar(planilha(tmp_path / "p.xlsx", linhas), CONTA)
    itens = motor.listar()
    assert len(itens) == 12
    assert not any("duplicidade" in i["motivos"] for i in itens)


def test_pix_iguais_sem_favorecido_vao_para_revisao(motor, tmp_path):
    linhas = [(25, "PIX ENVIADO", None, 500), (25, "PIX ENVIADO", None, 500)]
    motor.importar(planilha(tmp_path / "p.xlsx", linhas), CONTA)
    itens = motor.listar()
    assert len(itens) == 2  # as duas são preservadas
    assert all("possível duplicidade" in i["motivos"] for i in itens)


def test_reimportar_planilha_nao_duplica(motor, tmp_path):
    arq = planilha(tmp_path / "p.xlsx", [(3, "PIX ENVIADO", "A", 100), (3, "PIX ENVIADO", "A", 100)])
    motor.importar(arq, CONTA)
    r = motor.importar(arq, CONTA)
    assert r.novas == 0 and r.ja_importadas == 2


def test_chave_de_transacao_sem_favorecido_nao_mudou():
    # Valor calculado pela versão anterior ao campo `favorecido`. Se mudar,
    # extratos importados antes passariam a ser duplicados na reimportação.
    chaves = calcular_chaves(ler_csv(EXEMPLOS / "extrato_exemplo.csv", "999-0001-12345-6"))
    assert chaves[1][0] == "99318f4555a059c0b3c0d4e52ef7f433"


def test_banco_de_versao_anterior_recebe_coluna_favorecido(tmp_path):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE transacoes (chave TEXT PRIMARY KEY, chave_conteudo TEXT NOT NULL,"
                " fitid TEXT, conta_bancaria TEXT NOT NULL, data TEXT NOT NULL, valor TEXT NOT NULL,"
                " historico TEXT NOT NULL, documento TEXT, origem TEXT NOT NULL,"
                " linha INTEGER NOT NULL, lote_id INTEGER NOT NULL)")
    con.commit()
    con.close()
    banco = BancoDeDados(caminho)
    colunas = {r["name"] for r in banco.conexao.execute("PRAGMA table_info(transacoes)")}
    banco.fechar()
    assert "favorecido" in colunas


# ------------------------------------------------------------------ classificação
def test_regra_nao_le_nome_do_favorecido(motor, tmp_path):
    # Erro encontrado nas planilhas reais: "FRANCISCO DAS CHAGAS" casava com
    # a regra do DAS e o PIX seria liberado como imposto.
    motor.importar(planilha(tmp_path / "p.xlsx", [
        (6, "PIX ENVIADO", "FRANCISCO DAS CHAGAS EXEMPLO", 2000),
    ]), CONTA)
    item = motor.listar()[0]
    assert item["status"] == "pendente"
    assert item["fonte"] == "nenhuma"


def test_regra_configurada_para_favorecido(motor, tmp_path):
    motor.importar(planilha(tmp_path / "p.xlsx", [
        (17, "PAGAMENTOS", "ENERGIA EXEMPLO DISTRIBUIDORA", 123.45),
        (29, "PAGAMENTOS", "SIMPLES NACIONAL", 2222.22),
    ]), CONTA)
    por_valor = {i["valor"]: i for i in motor.listar()}
    assert por_valor["-123.45"]["status"] == "liberado"
    assert por_valor["-123.45"]["conta_debito"] == "4.2.1.02.001"
    assert por_valor["-2222.22"]["fonte"] == "regra:das-favorecido"
    assert "PAGAMENTOS - SIMPLES NACIONAL" in por_valor["-2222.22"]["historico"]


@pytest.mark.parametrize("lanc, desc, alerta", [
    ("SANTOS", None, ALERTA_SEM_TIPO),                        # pedaço de nome sem operação
    ("PAGAMENTOS", "SIMPLES NACIONAL FULANO DE TAL SOBRENOME", ALERTA_DOIS_NOMES),
    ("IOF", "FULANO DE TAL", ALERTA_ENCARGO_COM_FAVORECIDO),  # encargo não tem favorecido
    ("JUROS LIMITE DA CONTA", "EMPRESA QUALQUER", ALERTA_ENCARGO_COM_FAVORECIDO),
])
def test_linha_mal_extraida_vai_para_revisao_mesmo_com_regra(motor, tmp_path, lanc, desc, alerta):
    motor.importar(planilha(tmp_path / "p.xlsx", [(5, lanc, desc, 12.34)]), CONTA)
    item = motor.listar()[0]
    assert item["status"] == "pendente"
    assert alerta in item["motivos"]


def test_alertas_nao_disparam_em_linhas_normais(tmp_path):
    ts = ler_planilha_despesas(planilha(tmp_path / "p.xlsx", [
        (5, "PAGAMENTOS", "SIMPLES NACIONAL", 10),
        (5, "TAR PLANO ADAPT 1 07/26", None, 150),
        (5, "BOLETO PAGO FORNECEDOR", "EMPRESA EXEMPLO LTDA", 50),
        (5, "IOF", None, 4.56),
    ]), CONTA)
    assert all(t.alertas == () for t in ts)
