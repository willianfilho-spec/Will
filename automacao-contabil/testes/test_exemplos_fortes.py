"""Testes dos arquivos-modelo fictícios de `exemplos/fortes/`.

Garantem que os exemplos entregues ao escritório continuam coerentes entre si
e com o motor: plano, regras, extratos (OFX, CSV, XLSX), arquivo de importação
do Fortes e ausência de dados reais.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from motor_contabil import empresas
from motor_contabil.conciliacao import confrontar, ler_importados
from motor_contabil.exportador_fortes import ExportadorFortes
from motor_contabil.leitores import ler_extrato
from motor_contabil.motor import MOTIVO_DUP_ARQUIVO, MOTIVO_DUP_BANCO
from motor_contabil.plano_contas import PlanoDeContas
from motor_contabil.regras import ConjuntoDeRegras

PASTA = Path(__file__).resolve().parent.parent / "exemplos" / "fortes"
PLANO = PASTA / "plano_contas_fortes.csv"
REGRAS = PASTA / "regras_fortes.json"
OFX = PASTA / "extrato_exemplo.ofx"
CSV_EXTRATO = PASTA / "extrato_exemplo.csv"
XLSX = PASTA / "planilha_despesas_exemplo.xlsx"
MODELO = PASTA / "modelo_importacao_fortes.csv"

BANCO = "362"
SALDO_INICIAL = Decimal("10000.00")
SALDO_FINAL = Decimal("17839.67")
MARCA = re.compile(rb" \[EX-\d{6}-[0-9A-F]{8}\]")


@pytest.fixture
def plano() -> PlanoDeContas:
    return PlanoDeContas.carregar_fortes(PLANO)


@pytest.fixture
def empresa(tmp_path):
    return empresas.cadastrar(
        tmp_path / "dados", "exemplo", "Empresa Exemplo Ltda", "11.222.333/0001-81", BANCO, "EX",
        "fortes", PLANO, REGRAS,
    )


@pytest.fixture
def motor(empresa):
    m = empresa.abrir_motor("teste")
    yield m
    m.banco.fechar()


def pares(transacoes) -> list[tuple[date, Decimal, str]]:
    return [(t.data, t.valor, t.historico) for t in transacoes]


# ------------------------------------------------------------------ E1
def test_e1_plano_carrega_e_banco_362_e_analitico(plano):
    banco = plano.por_reduzido(BANCO)
    assert banco is not None
    assert banco.descricao == "Banco Itaú"
    assert banco.analitica
    assert len(plano.analiticas()) > 10


def test_e1_nenhum_reduzido_repetido_no_arquivo():
    texto = PLANO.read_bytes().decode("cp1252")
    reduzidos = [campos[2].strip() for campos in csv.reader(texto.splitlines(), delimiter=";")
                 if campos and campos[2].strip()]
    assert reduzidos and len(reduzidos) == len(set(reduzidos))


def test_e1_formato_do_plano_como_exportado_pelo_fortes():
    bruto = PLANO.read_bytes()
    bruto.decode("cp1252")  # não levanta: o arquivo é cp1252 válido
    assert b"\r\n" in bruto and b"\n" not in bruto.replace(b"\r\n", b"")
    for linha in bruto.decode("cp1252").split("\r\n")[:-1]:
        campos = next(csv.reader([linha], delimiter=";"))
        assert len(campos) == 6
        # campos 1, 2 e 6 entre aspas (3 pares)
        assert re.match(r'^"[^"]*";"[^"]*";[^";]*;[^";]*;[^";]*;"[^"]*"$', linha), linha


def test_e1_plano_e_regras_combinam(plano):
    regras = ConjuntoDeRegras.carregar(REGRAS)
    assert empresas.validar_configuracao(plano, regras) == []


def test_e1_nomes_ficticios_de_clientes_e_fornecedores(plano):
    nomes = [c.descricao for c in plano.analiticas()]
    assert any(re.fullmatch(r"CLIENTE EXEMPLO \d\d LTDA", n) for n in nomes)
    assert any(re.fullmatch(r"FORNECEDOR EXEMPLO \d\d LTDA", n) for n in nomes)


# ------------------------------------------------------------------ E2
def test_e2_ofx_e_csv_dao_os_mesmos_13_movimentos():
    ofx = ler_extrato(OFX, BANCO)
    csv_ = ler_extrato(CSV_EXTRATO, BANCO)
    assert len(ofx) == len(csv_) == 13
    assert pares(ofx) == pares(csv_)


def test_e2_xlsx_da_exatamente_as_saidas_do_ofx_com_valor_negativo():
    ofx = ler_extrato(OFX, BANCO)
    xlsx = ler_extrato(XLSX, BANCO)
    saidas = [p for p in pares(ofx) if p[1] < 0]
    assert len(xlsx) == len(saidas) == 11
    assert all(t.valor < 0 for t in xlsx)
    assert pares(xlsx) == saidas


def test_e2_saldo_inicial_mais_movimentos_fecha_no_saldo_final():
    ofx = ler_extrato(OFX, BANCO)
    assert SALDO_INICIAL + sum((t.valor for t in ofx), Decimal("0")) == SALDO_FINAL
    assert sum((t.valor for t in ofx if t.valor > 0), Decimal("0")) == Decimal("23420.15")
    assert sum((t.valor for t in ofx if t.valor < 0), Decimal("0")) == Decimal("-15580.48")


def test_e2_csv_ignora_as_linhas_saldo():
    texto = CSV_EXTRATO.read_bytes().decode("cp1252")
    assert "SALDO ANTERIOR" in texto and "SALDO DO DIA" in texto
    historicos = [t.historico for t in ler_extrato(CSV_EXTRATO, BANCO)]
    assert len(historicos) == 13
    assert not any("SALDO" in h.upper() for h in historicos)


# ------------------------------------------------------------------ E3
def _importar_ofx(motor):
    return motor.importar(OFX, BANCO)


def test_e3_importar_ofx_classifica_por_regra_e_deixa_pendentes(motor):
    r = _importar_ofx(motor)
    assert (r.lidas, r.novas, r.ja_importadas) == (13, 13, 0)
    assert r.total_entradas == Decimal("23420.15")
    assert r.total_saidas == Decimal("-15580.48")
    # Números reais: 8 liberados por regra e 5 pendentes (2 PIX iguais, 2 funcionários e o sócio).
    assert Counter(i["status"] for i in motor.listar()) == {"liberado": 8, "pendente": 5}
    fontes = {i["historico_banco"]: i["fonte"] for i in motor.listar()}
    por_regra = Counter(i["fonte"] for i in motor.listar() if i["status"] == "liberado")
    assert por_regra == {
        "regra:tarifa": 1, "regra:das": 1, "regra:iof-juros": 2,
        "regra:fornecedor-01": 2,
        "regra:cliente-01": 1, "regra:cliente-02": 1,
    }, fontes
    pendentes = sorted(i["historico_banco"] for i in motor.listar("pendente"))
    assert pendentes == [
        "PIX ENVIADO FORNECEDOR EXEMPLO 02 LTDA", "PIX ENVIADO FORNECEDOR EXEMPLO 02 LTDA",
        "PIX ENVIADO FUNCIONARIO EXEMPLO A", "PIX ENVIADO FUNCIONARIO EXEMPLO B",
        "PIX ENVIADO SOCIO EXEMPLO",
    ]


def test_e3_os_dois_pix_iguais_ao_fornecedor_02_ficam_pendentes_por_duplicidade(motor):
    """Mesmo documento (101502), FITIDs distintos: a regra casa, mas vai para revisão."""
    _importar_ofx(motor)
    pix = [i for i in motor.listar() if i["historico_banco"] == "PIX ENVIADO FORNECEDOR EXEMPLO 02 LTDA"]
    assert len(pix) == 2
    assert {i["documento"] for i in pix} == {"101502"}
    assert len({i["chave"] for i in pix}) == 2
    for i in pix:
        assert i["status"] == "pendente"
        assert i["fonte"] == "regra:fornecedor-02"
        assert i["conta_contrapartida"] == "2.01.01.01.01.0003-6"
        assert MOTIVO_DUP_ARQUIVO in i["motivos"]


def _aprovar_como_no_modelo(motor, plano):
    for i in motor.listar("pendente"):
        if "SOCIO" in i["historico_banco"]:
            conta = plano.por_reduzido("375").codigo
        elif "FUNCIONARIO" in i["historico_banco"]:
            conta = plano.por_reduzido("63").codigo
        else:  # PIX iguais: aprova com a conta sugerida pela regra
            conta = None
        motor.aprovar(i["chave"], conta)


def _exportar(motor, plano, tmp_path) -> bytes:
    destino = tmp_path / "saida.csv"
    lote, quantidade = motor.exportar(destino, ExportadorFortes(plano, "EX"))
    assert lote is not None and quantidade == 13
    return destino.read_bytes()


def test_e3_aprovar_e_exportar_marcas_diferentes_para_cada_linha(motor, plano, tmp_path):
    _importar_ofx(motor)
    _aprovar_como_no_modelo(motor, plano)
    assert Counter(i["status"] for i in motor.listar()) == {"liberado": 13}
    gerado = _exportar(motor, plano, tmp_path)
    esperado = MODELO.read_bytes()
    assert len(MARCA.findall(gerado)) == len(MARCA.findall(esperado)) == 13
    assert len(set(MARCA.findall(gerado))) == 13


def test_e3_exportacao_byte_a_byte_igual_ao_modelo(motor, plano, tmp_path):
    _importar_ofx(motor)
    _aprovar_como_no_modelo(motor, plano)
    assert _exportar(motor, plano, tmp_path) == MODELO.read_bytes()


# ------------------------------------------------------------------ E4
def test_e4_modelo_em_ascii_crlf_e_9_campos():
    bruto = MODELO.read_bytes()
    texto = bruto.decode("ascii")
    assert texto.endswith("\r\n")
    assert "\n" not in texto.replace("\r\n", "")
    linhas = texto.split("\r\n")[:-1]
    assert len(linhas) == 13
    padrao = re.compile(r"^\d\d/\d\d/\d{4};\d+;\d+;\d+,\d\d;[ -:<-~]{1,118};;;;$")
    for linha in linhas:
        assert padrao.match(linha), linha
        assert len(linha.split(";")) == 9


def test_e4_contas_do_modelo_existem_e_sao_analiticas(plano):
    aceitos = ler_importados(MODELO)
    assert len(aceitos) == 13
    for a in aceitos:
        for reduzido in (a.debito, a.credito):
            conta = plano.por_reduzido(reduzido)
            assert conta is not None, f"reduzido {reduzido} fora do plano"
            assert conta.analitica
        assert BANCO in (a.debito, a.credito)
        assert a.valor > 0


def test_e4_modelo_confronta_com_o_csv_sem_sobras():
    c = confrontar(ler_extrato(CSV_EXTRATO, BANCO), ler_importados(MODELO), BANCO)
    assert c.pareados == 13
    assert c.so_no_extrato == []
    assert c.so_na_contabilidade == []


# ------------------------------------------------------------------ E5
def test_e5_reimportar_o_mesmo_ofx_nao_cria_transacoes(motor):
    primeira = _importar_ofx(motor)
    antes = motor.listar()
    segunda = _importar_ofx(motor)
    assert (segunda.lidas, segunda.novas, segunda.ja_importadas) == (13, 0, 13)
    assert segunda.arquivo_ja_visto_no_lote == primeira.lote_id
    assert motor.listar() == antes


def test_e5_csv_depois_do_ofx_cria_13_pendentes_por_possivel_duplicidade(motor):
    """Comportamento real: o CSV não tem FITID, então a chave difere da do OFX.

    Nada é liberado de novo: as 13 transações novas entram pendentes, com o
    motivo de possível duplicidade apontando para o que já foi importado. A
    barreira é a revisão humana (chave_conteudo), não o descarte automático.
    """
    _importar_ofx(motor)
    r = motor.importar(CSV_EXTRATO, BANCO)
    assert (r.lidas, r.novas, r.ja_importadas) == (13, 13, 0)
    assert sum(r.por_status.values()) == 13
    todos = motor.listar()
    assert len(todos) == 26
    assert Counter(i["status"] for i in todos) == {"liberado": 8, "pendente": 18}
    do_csv = [i for i in todos if i["origem"].endswith(".csv") or i["origem"] == CSV_EXTRATO.name]
    assert len(do_csv) == 13
    assert all(i["status"] == "pendente" and MOTIVO_DUP_BANCO in i["motivos"] for i in do_csv)


# ------------------------------------------------------------------ E6
TERMOS_PROIBIDOS = ["ARAUJO", "62.064", "OLAVO", "NAYNE", "MRV", "CANOPUS", "SIQUE"]


def _textos(caminho: Path) -> list[str]:
    bruto = caminho.read_bytes()
    pedacos = [bruto.decode("latin-1")]
    if zipfile.is_zipfile(io.BytesIO(bruto)):
        with zipfile.ZipFile(io.BytesIO(bruto)) as z:
            pedacos += [z.read(n).decode("utf-8", "replace") for n in z.namelist()]
            pedacos += list(z.namelist())
    return pedacos


def test_e6_exemplos_nao_tem_dados_reais():
    arquivos = [p for p in PASTA.rglob("*") if p.is_file()]
    assert len(arquivos) >= 6
    for caminho in arquivos:
        for texto in _textos(caminho):
            alto = texto.upper()
            for termo in TERMOS_PROIBIDOS:
                assert termo not in alto, f"{termo!r} em {caminho.name}"
            sem_acento = re.sub("[ÁÀÂÃ]", "A", alto)
            assert "ARAUJO" not in sem_acento and "ARAÚJO" not in alto, caminho.name
