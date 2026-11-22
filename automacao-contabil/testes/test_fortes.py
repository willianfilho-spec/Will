from __future__ import annotations

from pathlib import Path

import pytest

from motor_contabil import (
    BancoDeDados, ConjuntoDeRegras, ErroDeExportacao, ExportadorFortes, Motor, PlanoDeContas, Status,
)

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"


@pytest.fixture
def plano():
    return PlanoDeContas.carregar(EXEMPLOS / "plano_contas.csv")


@pytest.fixture
def motor(tmp_path, plano):
    regras = ConjuntoDeRegras.carregar(EXEMPLOS / "regras.json")
    m = Motor(BancoDeDados(tmp_path / "teste.db"), plano, regras)
    yield m
    m.banco.fechar()


def item(**mudancas) -> dict:
    base = {
        "chave": "a1b2c3d4e5f60718", "data": "2026-10-06", "valor": "-5000.00",
        "historico": "Pagamento a fornecedor - PIX ENVIADO AÇÃO; GESSO",
        "conta_debito": "2.1.1.01.001", "conta_credito": "1.1.1.02.001",
    }
    return base | mudancas


def test_leiaute_fortes_byte_a_byte(plano, tmp_path):
    destino = tmp_path / "fortes.csv"
    ExportadorFortes(plano, "NX").escrever([item()], destino)
    assert destino.read_bytes() == (
        b"06/10/2026;101;5;5000,00;"
        b"PAGAMENTO A FORNECEDOR - PIX ENVIADO ACAO, GESSO [NX-202610-A1B2C3D4];;;;\r\n"
    )


def test_nove_campos_sem_cabecalho_e_so_ascii(plano, tmp_path):
    destino = tmp_path / "fortes.csv"
    itens = [item(), item(chave="ffff000011112222", valor="1234567.89", conta_debito="1.1.1.02.001",
                          conta_credito="1.1.2.01.001", historico="Recebimento – cliente nº 7")]
    ExportadorFortes(plano).escrever(itens, destino)
    conteudo = destino.read_bytes()
    assert all(byte < 128 for byte in conteudo)
    linhas = conteudo.decode("ascii").split("\r\n")
    assert linhas[-1] == "" and len(linhas) == 3
    for linha in linhas[:-1]:
        assert len(linha.split(";")) == 9
    assert linhas[1].split(";")[3] == "1234567,89"  # sem separador de milhar


def test_historico_longo_cabe_em_118_e_mantem_a_marca(plano):
    linha = ExportadorFortes(plano, "NX").linhas([item(historico="X" * 300)])[0]
    historico = linha.split(";")[4]
    assert len(historico) == 118
    assert historico.endswith("[NX-202610-A1B2C3D4]")


def test_operacoes_iguais_geram_linhas_diferentes(plano):
    linhas = ExportadorFortes(plano).linhas([item(), item(chave="0000aaaa1111bbbb")])
    assert len(set(linhas)) == 2


@pytest.mark.parametrize("mudanca, trecho", [
    ({"conta_debito": "9.9.9"}, "não existe no plano"),
    ({"conta_debito": "4"}, "sintética"),
    ({"conta_debito": None}, "não existe no plano"),
    ({"valor": "0.00"}, "valor zero"),
    ({"conta_debito": "1.1.1.02.001"}, "mesma conta reduzida"),
])
def test_problema_impede_o_lote_inteiro(plano, tmp_path, mudanca, trecho):
    destino = tmp_path / "fortes.csv"
    with pytest.raises(ErroDeExportacao, match=trecho):
        ExportadorFortes(plano).escrever([item(), item(chave="bbbb", **mudanca)], destino)
    assert not destino.exists()  # nada de arquivo parcial


def test_conta_sem_reduzido_numerico_nao_exporta(tmp_path):
    arquivo = tmp_path / "plano.csv"
    arquivo.write_text(
        "codigo;descricao;tipo;codigo_exportacao\n1.1;Banco;A;5\n2.1;Fornecedor;A;\n", encoding="utf-8"
    )
    plano = PlanoDeContas.carregar(arquivo)
    with pytest.raises(ErroDeExportacao, match="sem código reduzido numérico"):
        ExportadorFortes(plano).linhas([item(conta_debito="2.1", conta_credito="1.1")])


def test_erro_no_exportador_fortes_nao_marca_como_exportado(motor, tmp_path):
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    liberados = len(motor.listar(Status.LIBERADO))
    assert liberados
    # Plano em que a conta do banco perdeu o código reduzido: o lote inteiro falha.
    arquivo = tmp_path / "plano.csv"
    texto = (EXEMPLOS / "plano_contas.csv").read_text(encoding="utf-8")
    arquivo.write_text(texto.replace("Conta Movimento;A;5", "Conta Movimento;A;"), encoding="utf-8")
    destino = tmp_path / "fortes.csv"
    with pytest.raises(ErroDeExportacao, match="sem código reduzido numérico"):
        motor.exportar(destino, ExportadorFortes(PlanoDeContas.carregar(arquivo)))
    assert not destino.exists()
    assert len(motor.listar(Status.LIBERADO)) == liberados
    assert not motor.lotes_exportacao()


def test_fluxo_completo_com_exportador_fortes(motor, tmp_path):
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    liberados = len(motor.listar(Status.LIBERADO))
    destino = tmp_path / "fortes.csv"
    lote, quantidade = motor.exportar(destino, ExportadorFortes(motor.plano))
    assert quantidade == liberados
    linhas = destino.read_bytes().decode("ascii").split("\r\n")[:-1]
    assert len(linhas) == liberados and len(set(linhas)) == liberados
    copia = tmp_path / "copia.csv"
    motor.reexportar(lote, copia)
    assert copia.read_bytes() == destino.read_bytes()


def test_plano_no_formato_do_fortes(tmp_path):
    arquivo = tmp_path / "plano_fortes.csv"
    arquivo.write_bytes(
        '"1";"*** Ativo ***";;;X;"Devedora"\r\n'
        '"1.01.01.02.01.0001-8";"Banco Ita\xfa";362;X;X;"Devedora"\r\n'
        '"2.01.01.01.01.0003-6";"FORNECEDOR EXEMPLO LTDA";368;X;X;"Credora"\r\n'.encode("latin-1")
    )
    plano = PlanoDeContas.carregar_fortes(arquivo)
    assert plano.problema("1") == "conta 1 é sintética e não aceita lançamento"
    banco = plano.por_reduzido("362")
    assert banco.descricao == "Banco Itaú" and banco.codigo == "1.01.01.02.01.0001-8"
    linha = ExportadorFortes(plano, "NX").linhas(
        [item(conta_debito="2.01.01.01.01.0003-6", conta_credito="1.01.01.02.01.0001-8")]
    )[0]
    assert linha.startswith("06/10/2026;368;362;5000,00;")


def test_plano_fortes_com_reduzido_repetido_e_recusado(tmp_path):
    arquivo = tmp_path / "plano_fortes.csv"
    arquivo.write_text('"1.1";"A";7;X\n"1.2";"B";7;X\n', encoding="utf-8")
    with pytest.raises(ValueError, match="reduzido repetido"):
        PlanoDeContas.carregar_fortes(arquivo)
