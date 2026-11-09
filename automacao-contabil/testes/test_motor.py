from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas, Status
from motor_contabil.classificador_ia import ClassificadorClaude, Sugestao
from motor_contabil.leitores import ler_csv, ler_ofx
from motor_contabil.texto import mascarar_documentos, para_decimal

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"
CONTA_CSV = "999-0001-12345-6"


@pytest.fixture
def plano():
    return PlanoDeContas.carregar(EXEMPLOS / "plano_contas.csv")


@pytest.fixture
def regras():
    return ConjuntoDeRegras.carregar(EXEMPLOS / "regras.json")


@pytest.fixture
def motor(tmp_path, plano, regras):
    m = Motor(BancoDeDados(tmp_path / "teste.db"), plano, regras)
    yield m
    m.banco.fechar()


def escrever_csv(caminho: Path, linhas: list[tuple[str, str, str]]) -> Path:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Data", "Histórico", "Valor"])
        w.writerows(linhas)
    return caminho


# ------------------------------------------------------------------ leitura
def test_valores_brasileiros():
    assert para_decimal("1.200,50") == Decimal("1200.50")
    assert para_decimal("-45,00") == Decimal("-45.00")
    assert para_decimal("45,00-") == Decimal("-45.00")
    assert para_decimal("(45,00)") == Decimal("-45.00")
    assert para_decimal("1200.50") == Decimal("1200.50")
    assert para_decimal("R$ 3.500,00 C") == Decimal("3500.00")
    with pytest.raises(ValueError):
        para_decimal("abc")


def test_le_ofx_sgml():
    ts = ler_ofx(EXEMPLOS / "extrato_exemplo.ofx")
    assert len(ts) == 5
    assert ts[0].conta_bancaria == "999-0001-12345-6"
    assert ts[0].valor == Decimal("-45.00")
    assert ts[0].fitid == "20261105001"
    assert ts[0].data.isoformat() == "2026-11-05"
    assert sum(t.valor for t in ts) == Decimal("255.00")


def test_le_csv_ignora_saldo_e_preserva_valores():
    ts = ler_csv(EXEMPLOS / "extrato_exemplo.csv", CONTA_CSV)
    assert len(ts) == 5  # a linha de SALDO ANTERIOR não é movimentação
    assert [t.valor for t in ts] == [
        Decimal("-45.00"), Decimal("-1200.00"), Decimal("-1200.00"),
        Decimal("-800.00"), Decimal("3500.00"),
    ]
    assert ts[0].historico == "TARIFA PACOTE DE SERVIÇOS"


def test_csv_com_colunas_entrada_e_saida(tmp_path):
    arq = tmp_path / "e.csv"
    arq.write_text("Data;Descrição;Crédito;Débito\n05/11/2026;TARIFA;;45,00\n06/11/2026;DEP;100,00;\n",
                   encoding="utf-8")
    ts = ler_csv(arq, CONTA_CSV)
    assert [t.valor for t in ts] == [Decimal("-45.00"), Decimal("100.00")]


# ------------------------------------------------------------------ duplicidade
def test_reprocessar_o_mesmo_ofx_nao_duplica(motor):
    r1 = motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    r2 = motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    assert r1.novas == 5
    assert r2.novas == 0 and r2.ja_importadas == 5
    assert r2.arquivo_ja_visto_no_lote == r1.lote_id
    assert len(motor.listar()) == 5


def test_reprocessar_o_mesmo_csv_nao_duplica(motor):
    motor.importar(EXEMPLOS / "extrato_exemplo.csv", CONTA_CSV)
    r2 = motor.importar(EXEMPLOS / "extrato_exemplo.csv", CONTA_CSV)
    assert r2.novas == 0
    assert len(motor.listar()) == 5


def test_duas_operacoes_iguais_legitimas_sao_preservadas_e_sinalizadas(motor):
    motor.importar(EXEMPLOS / "extrato_exemplo.csv", CONTA_CSV)
    fornecedores = [i for i in motor.listar() if "FORNECEDOR" in i["historico_banco"]]
    assert len(fornecedores) == 2  # nenhuma das duas some
    assert all(i["status"] == "pendente" for i in fornecedores)
    assert all("possível duplicidade" in i["motivos"] for i in fornecedores)


def test_extratos_com_periodo_sobreposto(motor, tmp_path):
    a = escrever_csv(tmp_path / "a.csv", [
        ("01/11/2026", "TARIFA MENSAL", "-10,00"),
        ("02/11/2026", "PAGTO FORNECEDOR X", "-50,00"),
        ("02/11/2026", "PAGTO FORNECEDOR X", "-50,00"),
    ])
    b = escrever_csv(tmp_path / "b.csv", [
        ("02/11/2026", "PAGTO FORNECEDOR X", "-50,00"),
        ("02/11/2026", "PAGTO FORNECEDOR X", "-50,00"),
        ("03/11/2026", "TARIFA MENSAL", "-10,00"),
    ])
    motor.importar(a, CONTA_CSV)
    r = motor.importar(b, CONTA_CSV)
    assert r.novas == 1 and r.ja_importadas == 2
    assert sum(Decimal(i["valor"]) for i in motor.listar()) == Decimal("-120.00")


def test_terceira_ocorrencia_nova_e_importada(motor, tmp_path):
    linha = ("02/11/2026", "PAGTO FORNECEDOR X", "-50,00")
    motor.importar(escrever_csv(tmp_path / "a.csv", [linha, linha]), CONTA_CSV)
    r = motor.importar(escrever_csv(tmp_path / "b.csv", [linha, linha, linha]), CONTA_CSV)
    assert r.novas == 1


def test_fitid_instavel_vira_possivel_duplicidade(motor, tmp_path):
    original = (EXEMPLOS / "extrato_exemplo.ofx").read_text(encoding="cp1252")
    redownload = tmp_path / "redownload.ofx"
    redownload.write_text(original.replace("<FITID>2026", "<FITID>X2026"), encoding="cp1252")
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    r = motor.importar(redownload)
    assert r.novas == 5  # FITIDs novos: a chave principal não reconhece...
    novos = [i for i in motor.listar() if i["origem"] == "redownload.ofx"]
    # ...mas nenhum é liberado: todos vão para revisão como possível duplicidade
    assert all(i["status"] == "pendente" for i in novos)
    assert all("já importada com outro identificador" in i["motivos"] for i in novos)


# ------------------------------------------------------------------ classificação
def test_regra_unica_libera_com_partidas_corretas(motor):
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    por_hist = {i["historico_banco"]: i for i in motor.listar()}
    tarifa = por_hist["TARIFA PACOTE DE SERVICOS"]
    assert tarifa["status"] == "liberado"
    assert (tarifa["conta_debito"], tarifa["conta_credito"]) == ("4.2.1.01.001", "1.1.1.02.001")
    receb = por_hist["RECEBIMENTO BOLETO CLIENTE BETA"]
    assert (receb["conta_debito"], receb["conta_credito"]) == ("1.1.1.02.001", "1.1.2.01.001")
    pix = por_hist["PIX ENVIADO JOAO DA SILVA 123.456.789-09"]
    assert pix["status"] == "pendente" and pix["conta_debito"] is None


def test_regras_conflitantes_nao_decidem_sozinhas(tmp_path, plano):
    dados = json.loads((EXEMPLOS / "regras.json").read_text(encoding="utf-8"))
    dados["regras"].append({"id": "outra", "padrao": "TARIFA", "sentido": "saida",
                            "conta": "4.2.1.04.001"})
    arq = tmp_path / "r.json"
    arq.write_text(json.dumps(dados), encoding="utf-8")
    m = Motor(BancoDeDados(tmp_path / "x.db"), plano, ConjuntoDeRegras.carregar(arq))
    m.importar(EXEMPLOS / "extrato_exemplo.ofx")
    tarifa = next(i for i in m.listar() if "TARIFA" in i["historico_banco"])
    assert tarifa["status"] == "pendente"
    assert "conflitantes" in tarifa["motivos"]


def test_regra_apontando_conta_sintetica_bloqueia(tmp_path, plano):
    dados = json.loads((EXEMPLOS / "regras.json").read_text(encoding="utf-8"))
    dados["regras"][0]["conta"] = "4"  # sintética
    arq = tmp_path / "r.json"
    arq.write_text(json.dumps(dados), encoding="utf-8")
    m = Motor(BancoDeDados(tmp_path / "x.db"), plano, ConjuntoDeRegras.carregar(arq))
    m.importar(EXEMPLOS / "extrato_exemplo.ofx")
    tarifa = next(i for i in m.listar() if "TARIFA" in i["historico_banco"])
    assert tarifa["status"] == "bloqueado"
    assert "sintética" in tarifa["motivos"]


class IAFalsa:
    def __init__(self, conta):
        self.conta = conta

    def sugerir(self, t, plano):
        return Sugestao(self.conta, "media", "teste")


def test_sugestao_da_ia_nunca_libera_sozinha(tmp_path, plano, regras):
    m = Motor(BancoDeDados(tmp_path / "x.db"), plano, regras, classificador=IAFalsa("2.1.1.01.001"))
    m.importar(EXEMPLOS / "extrato_exemplo.ofx")
    pix = next(i for i in m.listar() if "PIX" in i["historico_banco"])
    assert pix["status"] == "pendente"
    assert pix["fonte"] == "ia"
    assert "sugestão da IA" in pix["motivos"]
    # a regra continua tendo prioridade sobre a IA
    tarifa = next(i for i in m.listar() if "TARIFA" in i["historico_banco"])
    assert tarifa["fonte"] == "regra:tarifa"


def test_classificador_claude_valida_resposta_e_minimiza_dados(plano):
    enviado = {}

    def criar(**kwargs):
        enviado.update(kwargs)
        texto = json.dumps({"conta": "9.9.9", "confianca": "alta", "justificativa": "x"})
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=texto)])

    cliente = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=criar)))
    ia = ClassificadorClaude(cliente=cliente)
    t = ler_ofx(EXEMPLOS / "extrato_exemplo.ofx")[3]  # PIX com CPF
    assert ia.sugerir(t, plano) is None  # conta inexistente é rejeitada
    mensagem = enviado["messages"][0]["content"]
    assert "123.456.789-09" not in mensagem and "[DOC]" in mensagem
    assert "800" not in mensagem.split("Movimentação:")[1]  # valor não enviado
    enum = enviado["output_config"]["format"]["schema"]["properties"]["conta"]["enum"]
    assert "4" not in enum and "4.2.1.01.001" in enum  # só analíticas


def test_classificador_claude_recusa_vira_pendencia(plano):
    resposta = SimpleNamespace(stop_reason="refusal", content=[])
    cliente = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: resposta)))
    t = ler_ofx(EXEMPLOS / "extrato_exemplo.ofx")[3]
    assert ClassificadorClaude(cliente=cliente).sugerir(t, plano) is None


def test_mascaramento():
    assert mascarar_documentos("PIX 123.456.789-09 E 12.345.678/0001-90") == "PIX [DOC] E [DOC]"
    assert mascarar_documentos("PIX 12345678909") == "PIX [DOC]"


# ------------------------------------------------------------------ revisão e exportação
def test_fluxo_completo_revisao_e_exportacao(motor, tmp_path):
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    pendentes = motor.listar(Status.PENDENTE)
    pix = next(i for i in pendentes if "PIX" in i["historico_banco"])
    fornecedores = [i for i in pendentes if "FORNECEDOR" in i["historico_banco"]]

    with pytest.raises(ValueError):
        motor.aprovar(pix["chave"])  # sem conta não há o que aprovar
    assert motor.aprovar(pix["chave"], conta="2.1.1.01.001").status == Status.LIBERADO
    # revisor confirma que os dois pagamentos são legítimos
    for f in fornecedores:
        assert motor.aprovar(f["chave"]).status == Status.LIBERADO

    saida = tmp_path / "lote1.csv"
    lote, n = motor.exportar(saida)
    assert n == 5
    linhas = list(csv.DictReader(saida.open(encoding="utf-8"), delimiter=";"))
    assert len(linhas) == 5
    # valores preservados ao centavo e códigos de exportação aplicados
    assert sorted(l["valor"] for l in linhas) == sorted(
        ["45,00", "1200,00", "1200,00", "800,00", "3500,00"])
    tarifa = next(l for l in linhas if l["valor"] == "45,00")
    assert (tarifa["conta_debito"], tarifa["conta_credito"]) == ("420", "5")
    assert tarifa["data"] == "05/11/2026"
    assert tarifa["origem"] == "extrato_exemplo.ofx#1"

    # exportar de novo não repete nada
    assert motor.exportar(tmp_path / "lote2.csv") == (None, 0)
    # e lançamento exportado não pode mais ser alterado
    with pytest.raises(ValueError):
        motor.aprovar(pix["chave"], conta="4.2.1.03.001")


def test_descarte_de_duplicidade(motor, tmp_path):
    motor.importar(EXEMPLOS / "extrato_exemplo.csv", CONTA_CSV)
    f1, f2 = [i for i in motor.listar() if "FORNECEDOR" in i["historico_banco"]]
    with pytest.raises(ValueError):
        motor.descartar(f2["chave"], "  ")
    motor.descartar(f2["chave"], "lançado em duplicidade pelo banco")
    motor.aprovar(f1["chave"])
    _, n = motor.exportar(tmp_path / "s.csv")
    assert n == 3  # tarifa, recebimento e um dos fornecedores
    eventos = motor.banco.conexao.execute(
        "SELECT acao FROM eventos WHERE chave=?", (f2["chave"],)).fetchall()
    assert [e["acao"] for e in eventos] == ["importado", "descartado"]


def test_falha_na_escrita_nao_marca_como_exportado(motor, tmp_path):
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    antes = len(motor.listar(Status.LIBERADO))

    class Quebrado:
        def escrever(self, itens, destino):
            raise OSError("disco cheio")

    with pytest.raises(OSError):
        motor.exportar(tmp_path / "x.csv", exportador=Quebrado())
    assert len(motor.listar(Status.LIBERADO)) == antes
