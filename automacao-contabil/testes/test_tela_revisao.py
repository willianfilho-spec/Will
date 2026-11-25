"""Tela de revisão (seção 2): aprovar, descartar e estados vazios, com dados fictícios."""

from __future__ import annotations

from io import BytesIO
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


def test_busca_ignora_acentos_e_aceita_o_codigo_do_lancamento(tela):
    at, pendentes = tela
    registro = next(i for i in pendentes if "FUNCIONARIO EXEMPLO A" in i["historico_banco"])
    unico = f"ok-{registro['chave']}"
    busca = next(i for i in at.text_input if i.label == "Buscar lançamentos")
    busca.set_value("funcionário exemplo a").run()
    assert [b.key for b in at.button if b.label == "Aprovar"] == [unico]
    busca = next(i for i in at.text_input if i.label == "Buscar lançamentos")
    busca.set_value(registro["chave"][:12].upper()).run()
    assert [b.key for b in at.button if b.label == "Aprovar"] == [unico]
    exportacao = next(b for b in at.button if b.label.startswith("Gerar arquivo de importação"))
    assert "(8 liberados)" in exportacao.label


def test_competencia_e_paginacao_respeitam_a_selecao(tela, tmp_path):
    at, _ = tela
    extrato = tmp_path / "novembro.csv"
    extrato.write_text(
        "Data;Histórico;Valor\n" + "".join(
            f"{dia:02}/11/2026;REVISAR EXEMPLO {dia};-10,00\n" for dia in range(1, 22)
        ), encoding="utf-8",
    )
    [empresa] = empresas.listar(tmp_path / "dados")
    motor = empresa.abrir_motor("revisora")
    try:
        assert motor.importar(extrato, "362").novas == 21
    finally:
        motor.banco.fechar()
    at.run()
    competencia = next(i for i in at.selectbox if i.label == "Competência")
    competencia.set_value("2026-11").run()
    assert len([b for b in at.button if b.label == "Aprovar"]) == 20
    pagina = next(i for i in at.selectbox if i.label == "Página de lançamentos")
    pagina.set_value(2).run()
    assert len([b for b in at.button if b.label == "Aprovar"]) == 1
    assert any("21 a 21 de 21" in c.value for c in at.caption)
    competencia = next(i for i in at.selectbox if i.label == "Competência")
    competencia.set_value("2026-10").run()
    assert len([b for b in at.button if b.label == "Aprovar"]) == 5
    assert not at.exception


def test_conferencia_e_pdf_permanecem_ao_mudar_filtro(tela):
    pytest.importorskip("pdfplumber")
    pytest.importorskip("reportlab")
    from reportlab.pdfgen.canvas import Canvas

    at, _ = tela
    buffer = BytesIO()
    pdf = Canvas(buffer)
    pdf.setFont("Helvetica", 9)
    for y, data, historico, x, valor in [
        (550, "30/09/2026", "SALDO ANTERIOR", 530, "0,00"),
        (530, "01/10/2026", "RECEBIMENTO EXEMPLO", 460, "55,00"),
        (510, "01/10/2026", "SALDO EM CONTA CORRENTE", 530, "55,00"),
    ]:
        pdf.drawString(40, y, data)
        pdf.drawString(90, y, historico)
        pdf.drawString(x, y, valor)
    pdf.save()
    extrato = next(w for w in at.file_uploader if w.label == "Extrato Itaú em PDF")
    importados = next(w for w in at.file_uploader if w.label == "Arquivos já importados no Fortes")
    extrato.set_value(("extrato-exemplo.pdf", buffer.getvalue(), "application/pdf"))
    importados.set_value([("importado-exemplo.csv", b"01/10/2026;362;358;55,00;EXEMPLO;;;;\r\n", "text/csv")])
    at.run()
    next(b for b in at.button if b.label == "Conferir").click().run()
    assert any("Conciliado: 1 movimento pareado" in s.value for s in at.success)
    at.segmented_control(key="filtro-status").set_value("liberado").run()
    assert any("Conciliado: 1 movimento pareado" in s.value for s in at.success)
    assert any("extrato" in c.value and "importado" in c.value for c in at.caption)
    assert any("Baixar relatório da conferência" in b.label for b in at.download_button)
    assert not at.exception
