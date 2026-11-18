import pytest

from parsers.comum import ErroEstrutural, sanitizar_texto
from parsers.fortes_plano_parser import ler_plano_fortes
from parsers.fortes_razao_parser import ler_lancamentos_fortes
from parsers.ofx_parser import ler_ofx
from parsers.tabular_parser import Mapeamento, extrair_movimentos, ler_tabela, sugerir_mapeamento
from tests.conftest import EXEMPLOS


def test_ofx_exemplo():
    e = ler_ofx((EXEMPLOS / "extrato_exemplo.ofx").read_bytes())
    assert len(e.movimentos) == 6
    assert e.movimentos[0] == {"linha": 1, "data": "2026-09-02", "valor_centavos": -4590,
                               "historico": "TARIFA PACOTE SERVICOS", "documento": None, "fitid": "A0001"}
    assert e.saldo_final_centavos == 91115 and e.conta == "12345-6"


def test_ofx_xml_sem_fechamento_e_com_erro():
    xml = b"<OFX><BANKTRANLIST><STMTTRN><DTPOSTED>20260101<TRNAMT>10,00<FITID>X<NAME>A</BANKTRANLIST></OFX>"
    assert ler_ofx(xml).movimentos[0]["valor_centavos"] == 1000
    with pytest.raises(ErroEstrutural, match="TRNAMT"):
        ler_ofx(b"<OFX><STMTTRN><DTPOSTED>20260101<FITID>X</STMTTRN></OFX>")
    with pytest.raises(ErroEstrutural, match="não é um arquivo OFX"):
        ler_ofx(b"qualquer coisa")


def test_csv_com_mapeamento():
    cols, linhas = ler_tabela((EXEMPLOS / "extrato_exemplo.csv").read_bytes(), "x.csv")
    s = sugerir_mapeamento(cols)
    assert s["data"] == "Data" and s["historico"] == "Histórico" and s["valor"] == "Valor"
    movs = extrair_movimentos(linhas, Mapeamento(data="Data", historico="Histórico", valor="Valor"))
    assert [m["valor_centavos"] for m in movs] == [-4590, 230000, -18000]


def test_csv_erro_estrutural_recusa_tudo():
    bruto = "Data;Hist;Valor\n01/10/2026;A;10,00\n32/10/2026;B;5,00\n02/10/2026;C;abc\n".encode()
    _, linhas = ler_tabela(bruto, "x.csv")
    with pytest.raises(ErroEstrutural) as e:
        extrair_movimentos(linhas, Mapeamento(data="Data", historico="Hist", valor="Valor"))
    assert len(e.value.problemas) == 2


def test_xlsx_entrada_saida(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Data", "Descrição", "Entrada", "Saída"])
    ws.append(["05/09/2026", "@PAGTO X", None, 100.5])
    ws.append(["06/09/2026", "Recebimento", 200, None])
    f = tmp_path / "a.xlsx"
    wb.save(f)
    _, linhas = ler_tabela(f.read_bytes(), "a.xlsx")
    movs = extrair_movimentos(linhas, Mapeamento(data="Data", historico="Descrição", entrada="Entrada", saida="Saída"))
    assert [m["valor_centavos"] for m in movs] == [-10050, 20000]
    assert movs[0]["historico"] == "PAGTO X"


def test_sanitizar():
    assert sanitizar_texto("=1+1") == "1+1"
    assert sanitizar_texto("-5,00 estorno") == "-5,00 estorno"
    assert sanitizar_texto("a\x00b\n c") == "ab c"


def test_plano_fortes():
    contas = ler_plano_fortes((EXEMPLOS / "plano_contas_fortes.csv").read_bytes())
    banco = next(c for c in contas if c["reduzido"] == "362")
    assert banco["aceita_lancamento"] == 1 and banco["natureza"] == "Devedora"
    assert next(c for c in contas if c["classificacao"] == "1")["aceita_lancamento"] == 0


def test_plano_latin1_e_reduzido_repetido():
    bruto = '"1.1";"Banco Exemplo Ação";7;X\n"1.2";"B";7;X\n'.encode("latin-1")
    with pytest.raises(ErroEstrutural, match="repetido"):
        ler_plano_fortes(bruto)
    assert ler_plano_fortes('"1.1";"Banco Exemplo Ação";7;X\n'.encode("latin-1"))[0]["descricao"] == "Banco Exemplo Ação"


def test_razao_no_leiaute_de_importacao():
    p = ler_lancamentos_fortes(b"27/08/2025;259;362;5600,00;PGTO [ALF-202508-000001];;;;\r\n")
    assert p == [
        {"data": "2025-08-27", "conta": "259", "debito_centavos": 560000, "credito_centavos": 0,
         "historico": "PGTO [ALF-202508-000001]"},
        {"data": "2025-08-27", "conta": "362", "debito_centavos": 0, "credito_centavos": 560000,
         "historico": "PGTO [ALF-202508-000001]"},
    ]
