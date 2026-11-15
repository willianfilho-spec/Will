from __future__ import annotations

import json
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas, Status
from motor_contabil.leitores import ler_extrato, ler_xlsx
from motor_contabil.sugerir_regras import ler_importados, parear, sugerir

CONTA = "BANCO_TESTE"


def coluna(i: int) -> str:
    return "ABCDEFGHIJ"[i]


def escrever_xlsx(caminho: Path, linhas: list[list], planilhas: int = 1) -> Path:
    """Gera um .xlsx mínimo, só com a biblioteca padrão (texto compartilhado e números)."""
    textos: list[str] = []
    xml_linhas = []
    for r, linha in enumerate(linhas, start=1):
        celulas = []
        for c, valor in enumerate(linha):
            ref = f"{coluna(c)}{r}"
            if valor is None:
                continue
            if isinstance(valor, str):
                textos.append(valor)
                celulas.append(f'<c r="{ref}" t="s"><v>{len(textos) - 1}</v></c>')
            else:
                celulas.append(f'<c r="{ref}"><v>{valor}</v></c>')
        xml_linhas.append(f'<row r="{r}">{"".join(celulas)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    folhas = "".join(f'<sheet name="P{i}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1, planilhas + 1))
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, planilhas + 1)
    )
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("xl/workbook.xml", f"<workbook {ns} {rns}><sheets>{folhas}</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   f"<sst {ns}>" + "".join(f"<si><t>{escape(t)}</t></si>" for t in textos) + "</sst>")
        for i in range(1, planilhas + 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {ns}><sheetData>{''.join(xml_linhas)}</sheetData></worksheet>")
    return caminho


CABECALHO = ["DATA", "LANÇAMENTO BANCÁRIO ", "DESCRIÇÃO ", "VALOR", "CAIXA/BANCO"]
# 46301 = 06/10/2026 no calendário do Excel
PLANILHA = [
    [None, "EMPRESA: TESTE LTDA"],
    ["DESPESAS"],
    CABECALHO,
    [46301, "BOLETO PAGO", "FORNECEDOR ALFA", "2312.8099999999999"],
    [46301, "TAR PLANO ADAPT 1 09/26", None, 169],
    [46302, None, None, 350],
    [None, None, None, "2831.81"],
]


def test_le_planilha_de_despesas(tmp_path):
    t = ler_extrato(escrever_xlsx(tmp_path / "abril.xlsx", PLANILHA), CONTA)
    assert [x.valor for x in t] == [Decimal("-2312.81"), Decimal("-169.00"), Decimal("-350.00")]
    assert t[0].data.isoformat() == "2026-10-06" and t[0].historico == "BOLETO PAGO FORNECEDOR ALFA"
    assert t[1].historico == "TAR PLANO ADAPT 1 09/26"
    assert t[2].historico == "SEM HISTORICO NA PLANILHA"  # movimento real, vai para revisão
    assert t[0].linha == 4 and t[0].origem == "abril.xlsx"


def test_coluna_sem_nome_entra_no_historico(tmp_path):
    linhas = [["DESPESAS"], ["DATA", "DESCRIÇÃO", None, "VALOR"], [46301, "PIX ENVIADO", "MARIA", 10]]
    assert ler_xlsx(escrever_xlsx(tmp_path / "p.xlsx", linhas), CONTA)[0].historico == "PIX ENVIADO MARIA"


def test_sem_titulo_vale_o_sinal(tmp_path):
    linhas = [["DATA", "HISTÓRICO", "VALOR"], [46301, "RECEBIMENTO", 100], [46301, "PAGAMENTO", -40]]
    assert [x.valor for x in ler_xlsx(escrever_xlsx(tmp_path / "p.xlsx", linhas), CONTA)] == [100, -40]


@pytest.mark.parametrize("linhas, trecho", [
    ([["DESPESAS"], CABECALHO, [None, "PIX ENVIADO", "SEM DATA", 10]], "movimento sem data"),
    ([["DESPESAS"], CABECALHO, [46301, "PIX", "X", -10]], "valor negativo"),
    ([["DESPESAS"], CABECALHO, [46301, "PIX", "X", 10, "CAIXA"]], "CAIXA/BANCO"),
    ([["DESPESAS"], CABECALHO, [46301, "PIX", "X", "10.005"]], "fração de centavo"),
    ([["SEM CABECALHO"], [46301, "PIX", "X", 10]], "cabeçalho"),
])
def test_planilha_com_problema_e_recusada(tmp_path, linhas, trecho):
    with pytest.raises(ValueError, match=trecho):
        ler_xlsx(escrever_xlsx(tmp_path / "p.xlsx", linhas), CONTA)


def test_mais_de_uma_planilha_e_recusada(tmp_path):
    with pytest.raises(ValueError, match="2 planilhas"):
        ler_xlsx(escrever_xlsx(tmp_path / "p.xlsx", PLANILHA, planilhas=2), CONTA)


def test_xlsx_exige_conta_bancaria(tmp_path):
    with pytest.raises(ValueError, match="informe a conta bancária"):
        ler_extrato(escrever_xlsx(tmp_path / "p.xlsx", PLANILHA))


def test_reimportar_planilha_nao_duplica(tmp_path):
    exemplos = Path(__file__).resolve().parent.parent / "exemplos"
    motor = Motor(BancoDeDados(tmp_path / "t.db"), PlanoDeContas.carregar(exemplos / "plano_contas.csv"),
                  ConjuntoDeRegras.carregar(exemplos / "regras.json"))
    arquivo = escrever_xlsx(tmp_path / "p.xlsx", PLANILHA)
    assert motor.importar(arquivo, CONTA).novas == 3
    assert motor.importar(arquivo, CONTA).novas == 0
    sem_historico = [i for i in motor.listar() if i["historico_banco"] == "SEM HISTORICO NA PLANILHA"]
    assert sem_historico[0]["status"] == Status.PENDENTE.value
    motor.banco.fechar()


# --------------------------------------------------------------- regras sugeridas
PLANO_FORTES = (
    '"1";"Ativo";;;X\n"1.1.01";"Banco";362;X\n"2.1.01";"Fornecedor Alfa";368;X\n'
    '"4.1.01";"Tarifas";333;X\n"4.1.02";"Salarios";63;X\n"4.1.03";"Bonificacoes";306;X\n'
    '"2.2.01";"Emprestimo socio";375;X\n'
)


def preparar(tmp_path):
    plano_arq = tmp_path / "plano.csv"
    plano_arq.write_text(PLANO_FORTES, encoding="utf-8")
    linhas = [["DESPESAS"], CABECALHO]
    aceitos = []
    movimentos = [
        (46301, "BOLETO PAGO", "FORNECEDOR ALFA", "100.00", "368"),
        (46310, "BOLETO PAGO", "FORNECEDOR ALFA", "250.00", "368"),
        (46301, "TAR PLANO ADAPT 1 09/26", None, "169.00", "333"),
        (46331, "TAR PLANO ADAPT 1 10/26", None, "169.00", "333"),
        (46301, "PIX ENVIADO", "JOAO", "1000.00", "63"),    # mesmo favorecido,
        (46305, "PIX ENVIADO", "JOAO", "300.00", "306"),    # contas diferentes
        (46302, "PIX ENVIADO", "SOCIA", "500.00", "375"),
        (46303, "PIX ENVIADO", "SOCIA", "700.00", "375"),
        (46304, "PIX ENVIADO", "UNICO", "50.00", "368"),    # só uma vez
    ]
    from datetime import date, timedelta
    for serial, tipo, fav, valor, conta in movimentos:
        linhas.append([serial, tipo, fav, valor])
        d = (date(1899, 12, 30) + timedelta(days=serial)).strftime("%d/%m/%Y")
        aceitos.append(f"{d};{conta};362;{valor.replace('.', ',')};HIST;;;;")
    aceitos.append("06/10/2026;362;999;5000,00;RECEBIMENTO NAO PAREADO;;;;")
    imp = tmp_path / "aceitos.csv"
    imp.write_bytes("\r\n".join(aceitos).encode("ascii"))
    t = ler_xlsx(escrever_xlsx(tmp_path / "p.xlsx", linhas), "362")
    return PlanoDeContas.carregar_fortes(plano_arq), parear(t, ler_importados(imp), "362")


def test_sugere_so_regras_consistentes(tmp_path):
    plano, pares = preparar(tmp_path)
    assert all(conta for _, conta in pares)
    regras, avisos = sugerir(pares, plano, nunca={"375"})
    por_conta = {r["conta"]: r for r in regras}
    assert set(por_conta) == {"2.1.01", "4.1.01"}  # fornecedor e tarifa
    assert por_conta["4.1.01"]["padrao"] == r"^TAR\ PLANO\ ADAPT\ \d+\ \d+/\d+$"
    assert not avisos


def test_regras_sugeridas_funcionam_no_motor(tmp_path):
    plano, pares = preparar(tmp_path)
    regras, _ = sugerir(pares, plano, nunca={"375"})
    arquivo = tmp_path / "regras.json"
    arquivo.write_text(json.dumps({"conta_banco": "1.1.01", "regras": regras}), encoding="utf-8")
    conjunto = ConjuntoDeRegras.carregar(arquivo)
    for t, conta in pares:
        c = conjunto.classificar(t)
        if c.conta_contrapartida:
            assert plano.get(c.conta_contrapartida).codigo_exportacao == conta
        if "JOAO" in t.historico or "SOCIA" in t.historico:
            assert c.conta_contrapartida is None


def test_par_ambiguo_nao_e_usado(tmp_path):
    plano, pares = preparar(tmp_path)
    from motor_contabil.sugerir_regras import LancamentoAceito
    t = pares[0][0]
    duplo = [LancamentoAceito(t.data, "368", "362", abs(t.valor)), LancamentoAceito(t.data, "333", "362", abs(t.valor))]
    assert parear([t], duplo, "362") == [(t, None)]
