"""Relatórios em PDF para revisão e auditoria (dados fictícios da pasta exemplos/fortes)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("reportlab")

from motor_contabil import empresas  # noqa: E402
from motor_contabil.conciliacao import confrontar, ler_importados, resumo_mensal  # noqa: E402
from motor_contabil.exportador_fortes import ExportadorFortes  # noqa: E402
from motor_contabil.leitores import ler_extrato  # noqa: E402
from motor_contabil.relatorios import (  # noqa: E402
    brl, calcular_indicadores, codigo_conferencia, coletar_processamento,
    relatorio_conciliacao, relatorio_processamento, totais_por_conta,
)

EX = Path(__file__).resolve().parent.parent / "exemplos" / "fortes"
APP = Path(__file__).resolve().parent.parent / "app.py"
OUTUBRO = (date(2026, 10, 1), date(2026, 10, 31))


def _texto(pdf: bytes, tmp_path: Path) -> str:
    pdfplumber = pytest.importorskip("pdfplumber")
    arq = tmp_path / "r.pdf"
    arq.write_bytes(pdf)
    with pdfplumber.open(arq) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


@pytest.fixture
def processado(tmp_path):
    """Importa o OFX de exemplo, revisa os pendentes como no LEIAME e exporta."""
    emp = empresas.cadastrar(tmp_path / "dados", "ex", "EMPRESA EXEMPLO LTDA", "00.000.000/0001-91",
                             "362", "EX", "fortes", EX / "plano_contas_fortes.csv", EX / "regras_fortes.json")
    motor = emp.abrir_motor("revisora")
    motor.importar(EX / "extrato_exemplo.ofx")
    pend = {(p["historico_banco"], p["valor"]): p["chave"] for p in motor.listar("pendente")}
    chaves = list(pend.values())
    motor.aprovar(chaves[0], "2.01.01.03.01.0010-4")
    motor.aprovar(chaves[1], "2.01.01.03.01.0010-4")
    motor.descartar(chaves[2], "teste de descarte")
    motor.exportar(tmp_path / "lote.csv", ExportadorFortes(emp.carregar_plano(), "EX"))
    yield emp, motor
    motor.banco.fechar()


def _dados(emp, motor):
    return coletar_processamento(motor.banco.conexao, emp.nome, emp.cnpj, "362", *OUTUBRO, emp.carregar_plano())


def test_indicadores_refletem_o_que_o_motor_fez(processado):
    emp, motor = processado
    ind = calcular_indicadores(_dados(emp, motor))
    assert ind.total == 13
    assert ind.entradas == Decimal("23420.15") and ind.saidas == Decimal("-15580.48")
    assert ind.automaticos == 8          # liberados por regra na importação, sem toque humano
    assert ind.revisados == 3            # 2 aprovados + 1 descartado
    assert ind.corrigidos == 2           # conta informada pelo revisor
    assert ind.em_aberto == 2            # os dois PIX iguais continuam pendentes
    assert ind.por_status["exportado"] == 10 and ind.por_status["descartado"] == 1


def test_totais_por_conta_batem_com_o_exportado(processado):
    emp, motor = processado
    linhas = totais_por_conta(_dados(emp, motor))
    assert sum(n for _, _, n, _, _ in linhas) == 10
    salarios = next(x for x in linhas if x[0] == "2.01.01.03.01.0010-4")
    assert salarios[2] == 2 and salarios[4] == Decimal("-3700.00")
    assert "red. 63" in salarios[1]


def test_periodo_sem_movimento_gera_relatorio_vazio(processado, tmp_path):
    emp, motor = processado
    d = coletar_processamento(motor.banco.conexao, emp.nome, emp.cnpj, "362",
                              date(2025, 1, 1), date(2025, 1, 31), emp.carregar_plano())
    assert calcular_indicadores(d).total == 0 and d.eventos == [] and d.lotes == []
    texto = _texto(relatorio_processamento(d, "revisora"), tmp_path)
    assert "Nenhuma transação importada com data neste período" in texto


def test_pdf_de_processamento_tem_as_secoes_de_auditoria(processado, tmp_path):
    emp, motor = processado
    pdf = relatorio_processamento(_dados(emp, motor), "revisora")
    assert pdf.startswith(b"%PDF")
    texto = _texto(pdf, tmp_path)
    for trecho in ("Relatório de processamento e revisão", "EMPRESA EXEMPLO LTDA", "01/10/2026 a 31/10/2026",
                   "Pendentes de revisão", "Bloqueados", "Descartados pelo revisor", "teste de descarte",
                   "Revisões feitas por pessoas", "Totais por conta", "Lotes de importação e exportação",
                   "Trilha de auditoria", "Revisão humana", "Código de conferência",
                   "Há 2 lançamento(s) em aberto"):
        assert trecho in texto, trecho


def test_codigo_de_conferencia_so_muda_com_os_dados(processado):
    emp, motor = processado
    a = _dados(emp, motor)
    b = _dados(emp, motor)
    chave = lambda d: codigo_conferencia({"l": d.lancamentos, "e": d.eventos})  # noqa: E731
    assert chave(a) == chave(b)
    motor.descartar(motor.listar("pendente")[0]["chave"], "outro descarte")
    assert chave(_dados(emp, motor)) != chave(a)


def test_gerar_relatorio_nao_altera_o_banco(processado):
    emp, motor = processado
    antes = motor.banco.conexao.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
    relatorio_processamento(_dados(emp, motor), "revisora")
    assert motor.banco.conexao.execute("SELECT COUNT(*) FROM eventos").fetchone()[0] == antes


def _conferencia(lote_csv: Path, motor):
    lido = ler_extrato(EX / "extrato_exemplo.ofx", "362")
    transacoes = getattr(lido, "transacoes", lido)
    aceitos = ler_importados(lote_csv)
    saldos = {date(2026, 9, 30): Decimal("10000.00"), date(2026, 10, 31): Decimal("17839.67")}
    return (resumo_mensal(transacoes, saldos, aceitos, "362", Decimal("10000")),
            confrontar(transacoes, aceitos, "362"), len(transacoes))


def test_pdf_de_conciliacao_nao_conciliado_lista_as_sobras(processado, tmp_path):
    emp, motor = processado
    linhas, total, n = _conferencia(tmp_path / "lote.csv", motor)
    assert len(total.so_no_extrato) == 3
    texto = _texto(relatorio_conciliacao(emp.nome, emp.cnpj, "362", linhas, total, "revisora",
                                         "extrato_exemplo.ofx", ["lote.csv"], None, n), tmp_path)
    assert "Não conciliado" in texto
    assert "Só no extrato" in texto and "PIX ENVIADO SOCIO EXEMPLO" in texto
    assert "não pelo razão emitido pelo Fortes" in texto


def test_pdf_de_conciliacao_com_o_modelo_completo_concilia(processado, tmp_path):
    emp, motor = processado
    linhas, total, n = _conferencia(EX / "modelo_importacao_fortes.csv", motor)
    texto = _texto(relatorio_conciliacao(emp.nome, emp.cnpj, "362", linhas, total, "revisora",
                                         "extrato_exemplo.ofx", ["modelo_importacao_fortes.csv"], None, n),
                   tmp_path)
    assert "Conciliado: saldo igual em todos os meses e nenhuma sobra." in texto
    assert brl(Decimal("17839.67")) in texto


def test_brl_com_milhar():
    assert brl(Decimal("-1234567.8")) == "-R$ 1.234.567,80"
    assert brl("0") == "R$ 0,00"


def test_interface_gera_relatorio_e_registra_download(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    dados = tmp_path / "dados"
    emp = empresas.cadastrar(dados, "ex", "EMPRESA EXEMPLO LTDA", "00.000.000/0001-91", "362", "EX",
                             "fortes", EX / "plano_contas_fortes.csv", EX / "regras_fortes.json")
    motor = emp.abrir_motor("revisora")
    motor.importar(EX / "extrato_exemplo.ofx")
    motor.banco.fechar()
    monkeypatch.setenv("MOTOR_CONTABIL_DADOS", str(dados))
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("5. Relatório de processamento" in s.value for s in at.subheader)
    botao = next(b for b in at.button if b.label == "Gerar relatório")
    botao.click().run()
    assert not at.exception
    assert any("13 transações, 8 classificadas por regra" in s.value for s in at.success)
    nome, conteudo = at.session_state["rel_proc_ex"]
    assert nome == "processamento_ex_20261001_20261031.pdf" and conteudo.startswith(b"%PDF")
