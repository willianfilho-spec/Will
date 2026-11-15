from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from motor_contabil.conciliacao import (
    LancamentoAceito, confrontar, ler_importados, resumo_mensal, saldo_contabil,
)
from motor_contabil.leitores.itau_pdf import conferir_saldos_diarios, separar
from motor_contabil.modelo import Transacao

BANCO = "362"


def t(dia: int, valor: str, mes: int = 10, hist: str = "MOV") -> Transacao:
    return Transacao(BANCO, date(2026, mes, dia), D(valor), hist)


def a(dia: int, deb: str, cred: str, valor: str, mes: int = 10) -> LancamentoAceito:
    return LancamentoAceito(date(2026, mes, dia), deb, cred, D(valor), "HIST", "arq.csv", dia)


EXTRATO = [t(1, "1000.00"), t(2, "-300.00"), t(2, "-300.00"), t(5, "-50.00", mes=11)]
CONTABIL = [a(1, "362", "2", "1000,00".replace(",", ".")), a(2, "56", "362", "300.00"),
            a(2, "63", "362", "300.00"), a(5, "333", "362", "50.00", mes=11),
            a(3, "222", "63", "999.00")]  # não mexe no banco
SALDOS = {date(2026, 9, 30): D("0"), date(2026, 10, 2): D("400.00"), date(2026, 11, 5): D("350.00")}


def test_tudo_confere():
    c = confrontar(EXTRATO, CONTABIL, BANCO)
    assert c.pareados == 4 and not c.so_no_extrato and not c.so_na_contabilidade
    linhas = resumo_mensal(EXTRATO, SALDOS, CONTABIL, BANCO)
    assert [(l.mes, l.saldo_extrato, l.diferenca) for l in linhas] == [
        ("2026-09", D("0"), D("0")), ("2026-10", D("400.00"), D("0")), ("2026-11", D("350.00"), D("0"))]


def test_lancamento_faltando_aparece_dos_dois_jeitos():
    contabil = CONTABIL[:2] + CONTABIL[3:]  # falta um dos dois pagamentos de 300
    c = confrontar(EXTRATO, contabil, BANCO)
    assert [x.valor for x in c.so_no_extrato] == [D("-300.00")]
    out = resumo_mensal(EXTRATO, SALDOS, contabil, BANCO)[1]
    assert out.diferenca == D("300.00") and out.so_extrato == 1


def test_erros_que_se_compensam_nao_passam():
    # Saldo final igual, mas um pagamento lançado no dia errado.
    contabil = [x if x.valor != D("300.00") or x.debito != "63" else a(3, "63", "362", "300.00")
                for x in CONTABIL]
    assert saldo_contabil(contabil, BANCO, date(2026, 11, 5)) == D("350.00")
    c = confrontar(EXTRATO, contabil, BANCO)
    assert len(c.so_no_extrato) == 1 and len(c.so_na_contabilidade) == 1


def test_sentido_errado_nao_pareia():
    contabil = [a(1, "2", "362", "1000.00")]  # banco a crédito em vez de débito
    c = confrontar([t(1, "1000.00")], contabil, BANCO)
    assert c.pareados == 0


def test_saldo_inicial_contabil():
    assert saldo_contabil([], BANCO, date(2026, 1, 1), D("10.00")) == D("10.00")


def test_le_arquivo_importado(tmp_path):
    arq = tmp_path / "imp.csv"
    arq.write_bytes(b"01/10/2026;362;2;1000,00;RECEB [X-1];;;;\r\n02/10/2026;56;362;300,00;PGTO [X-2];;;;\r\n")
    aceitos = ler_importados(arq)
    assert aceitos[1] == LancamentoAceito(date(2026, 10, 2), "56", "362", D("300.00"), "PGTO [X-2]", "imp.csv", 2)


# --------------------------------------------------- conferência interna do extrato em PDF
def linha(d: date, hist: str, valor=None, saldo=None, ordem=0) -> dict:
    return {"data": d, "historico": hist, "contraparte": "", "documento": None,
            "valor": valor, "saldo": saldo, "pagina": 1, "ordem": ordem}


def test_extrato_que_confere():
    linhas = [linha(date(2026, 9, 30), "SALDO ANTERIOR", saldo=D("100")),
              linha(date(2026, 10, 1), "PIX ENVIADO PIX ENVIADO FULANO", valor=D("-40"), ordem=1),
              linha(date(2026, 10, 1), "SALDO TOTAL DISPONÍVEL DIA", saldo=D("60"), ordem=2)]
    movimentos, saldos = separar(linhas)
    assert movimentos[0]["historico"] == "PIX ENVIADO" and movimentos[0]["contraparte"] == "FULANO"
    assert conferir_saldos_diarios(movimentos, saldos) == (1, [])


def test_extrato_com_movimento_mal_lido_e_apontado():
    linhas = [linha(date(2026, 9, 30), "SALDO ANTERIOR", saldo=D("100")),
              linha(date(2026, 10, 1), "TARIFA", valor=D("-4"), ordem=1),
              linha(date(2026, 10, 1), "SALDO TOTAL DISPONÍVEL DIA", saldo=D("60"), ordem=2)]
    dias, divergencias = conferir_saldos_diarios(*separar(linhas))
    assert len(divergencias) == 1 and "imprime 60" in divergencias[0]
