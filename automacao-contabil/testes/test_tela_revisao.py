"""Tela de revisão (seção 2): aprovar, descartar e estados vazios, com dados fictícios."""

from __future__ import annotations

from pathlib import Path

import pytest

from motor_contabil import empresas

EX = Path(__file__).resolve().parent.parent / "exemplos" / "fortes"
APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def tela(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    dados = tmp_path / "dados"
    emp = empresas.cadastrar(dados, "ex", "EMPRESA EXEMPLO LTDA", "00.000.000/0001-91", "362", "EX",
                             "fortes", EX / "plano_contas_fortes.csv", EX / "regras_fortes.json")
    motor = emp.abrir_motor("revisora")
    motor.importar(EX / "extrato_exemplo.ofx")
    pendentes = motor.listar("pendente")
    motor.banco.fechar()
    monkeypatch.setenv("MOTOR_CONTABIL_DADOS", str(dados))
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    return at, pendentes


def _metricas(at) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def test_contagem_e_filtro_comecam_nos_pendentes(tela):
    at, pendentes = tela
    assert _metricas(at) == {"Pendentes": "5", "Bloqueados": "0", "Liberados": "8", "Exportados": "0"}
    assert at.segmented_control(key="filtro-status").value == "pendente"
    assert len(pendentes) == 5


def test_aprovar_sem_conta_fica_desabilitado(tela):
    at, pendentes = tela
    sem_regra = next(p for p in pendentes if p["conta_contrapartida"] is None)
    assert at.button(key=f"ok-{sem_regra['chave']}").disabled


def test_aprovar_com_conta_libera(tela):
    at, pendentes = tela
    chave = next(p for p in pendentes if p["conta_contrapartida"] is None)["chave"]
    at.selectbox(key=f"conta-{chave}").set_value("2.01.01.03.01.0010-4").run()
    at.button(key=f"ok-{chave}").click().run()
    assert not at.exception
    assert _metricas(at)["Pendentes"] == "4" and _metricas(at)["Liberados"] == "9"


def test_descartar_exige_motivo(tela):
    at, pendentes = tela
    chave = pendentes[0]["chave"]
    assert at.button(key=f"x-{chave}").disabled
    at.text_input(key=f"mot-{chave}").set_value("duplicado pelo banco").run()
    at.button(key=f"x-{chave}").click().run()
    assert not at.exception
    assert _metricas(at)["Pendentes"] == "4"
    at.segmented_control(key="filtro-status").set_value("descartado").run()
    assert not at.info  # o descartado aparece na lista


def test_filtro_sem_itens_mostra_estado_vazio(tela):
    at, _ = tela
    at.segmented_control(key="filtro-status").set_value("bloqueado").run()
    assert [i.value for i in at.info] == ["Nenhum lançamento bloqueado."]
