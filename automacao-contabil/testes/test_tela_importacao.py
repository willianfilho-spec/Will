"""Testes da tela "Importar extrato": lógica pura (tela_importacao.py) e estados do app.py.

Só dados fictícios. Arquivos de teste são gerados em tmp_path; o leiaute do Fortes
continua protegido por test_leiaute_fortes_byte_a_byte (test_fortes.py).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from motor_contabil import ExportadorFortes, Status, empresas
from motor_contabil.tela_importacao import (
    EXTENSOES_ACEITAS, TAMANHO_MAXIMO, RelatorioImportacao, formatar_moeda, processar_importacao,
    traduzir_erro, validar_envio,
)

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "exemplos"
OFX = EXEMPLOS / "extrato_exemplo.ofx"
APP = RAIZ / "app.py"


# ---------------------------------------------------------------- apoio
def _cadastrar(dados: Path):
    return empresas.cadastrar(
        dados, "alfa", nome="Alfa", cnpj="11.111.111/0001-11", conta_bancaria="BANCO_1",
        prefixo_marca="AL", formato_plano="motor", plano=EXEMPLOS / "plano_contas.csv",
        regras=EXEMPLOS / "regras.json",
    )


@pytest.fixture
def empresa(tmp_path):
    return _cadastrar(tmp_path / "dados")


@pytest.fixture
def motor(empresa):
    m = empresa.abrir_motor("teste")
    yield m
    m.banco.fechar()


def _lotes(motor) -> int:
    return motor.banco.conexao.execute("SELECT COUNT(*) FROM lotes").fetchone()[0]


def _arquivos(empresa) -> list[Path]:
    return [p for p in empresa.pasta_arquivos.rglob("*") if p.is_file()]


def _sem_traceback(rel: RelatorioImportacao) -> None:
    texto = f"{rel.titulo} {rel.detalhe} {rel.o_que_fazer}"
    assert "Traceback" not in texto
    assert 'File "' not in texto


def _recusado(rel: RelatorioImportacao) -> None:
    assert rel.ok is False
    assert rel.titulo == "Arquivo não importado"
    assert rel.detalhe.strip() and rel.o_que_fazer.strip()
    _sem_traceback(rel)


CSV_FICTICIO = (
    "Data;Histórico;Documento;Valor\n"
    "01/12/2026;SALDO ANTERIOR;;1.000,00\n"
    "02/12/2026;COMPRA MATERIAL ESCRITORIO;;-10,50\n"
    "03/12/2026;RECEBIMENTO CLIENTE GAMA;;250,25\n"
    "05/12/2026;TARIFA MENSAL;;-4,75\n"
)


# ---------------------------------------------------------------- C1
def test_c1_ofx_mostra_resultado_completo(motor, empresa):
    rel = processar_importacao(motor, empresa, OFX.name, OFX.read_bytes())
    itens = motor.listar()
    assert rel.ok and rel.titulo == "Extrato importado"
    assert (rel.lidas, rel.novas, rel.ja_importadas) == (5, 5, 0)
    assert len(itens) == 5
    for status, campo in ((Status.LIBERADO, rel.liberados), (Status.PENDENTE, rel.pendentes),
                          (Status.BLOQUEADO, rel.bloqueados)):
        assert campo == sum(1 for i in itens if i["status"] == status.value)
    assert rel.liberados + rel.pendentes + rel.bloqueados == rel.novas
    # entradas e saídas conferidas contra o banco (saídas saem com sinal negativo)
    assert rel.total_entradas == sum(Decimal(i["valor"]) for i in itens if Decimal(i["valor"]) > 0)
    assert rel.total_saidas == sum(Decimal(i["valor"]) for i in itens if Decimal(i["valor"]) < 0)
    assert rel.total_entradas == Decimal("3500.00") and rel.total_saidas == Decimal("-3245.00")
    assert (rel.primeira_data, rel.ultima_data) == (date(2026, 11, 5), date(2026, 11, 7))
    assert rel.lote_id is not None and rel.lote_id >= 1
    lote = motor.banco.conexao.execute("SELECT tipo FROM lotes WHERE id=?", (rel.lote_id,)).fetchone()
    assert lote["tipo"] != "exportacao"
    assert len(_arquivos(empresa)) == 1


def test_c1_csv_ficticio_mostra_resultado_completo(motor, empresa):
    rel = processar_importacao(motor, empresa, "dezembro.csv", CSV_FICTICIO.encode("utf-8"))
    itens = motor.listar()
    assert rel.ok
    assert rel.lidas == 3 and rel.novas == 3 and rel.ja_importadas == 0  # a linha de saldo não conta
    assert len(itens) == 3 and {i["conta_bancaria"] for i in itens} == {"BANCO_1"}  # vem do cadastro
    assert rel.total_entradas == Decimal("250.25")
    assert rel.total_saidas == Decimal("-15.25")
    assert (rel.primeira_data, rel.ultima_data) == (date(2026, 12, 2), date(2026, 12, 5))
    assert rel.liberados + rel.pendentes + rel.bloqueados == 3
    assert rel.lote_id is not None


# ---------------------------------------------------------------- C2
def test_c2_reimportar_o_mesmo_arquivo(motor, empresa):
    primeiro = processar_importacao(motor, empresa, OFX.name, OFX.read_bytes())
    antes = motor.listar()
    segundo = processar_importacao(motor, empresa, OFX.name, OFX.read_bytes())
    assert segundo.ok is True
    assert segundo.titulo == "Nada de novo neste extrato"
    assert segundo.novas == 0 and segundo.lidas == 5 and segundo.ja_importadas == 5
    assert any(f"lote {primeiro.lote_id}" in a for a in segundo.avisos)
    assert any("Nenhuma transação nova" in a for a in segundo.avisos)
    assert motor.listar() == antes  # nenhum lançamento novo nem alterado
    assert len(_arquivos(empresa)) == 1  # o original não é gravado duas vezes


# ---------------------------------------------------------------- C3
INVALIDOS = [
    pytest.param("extrato.docx", b"PK conteudo qualquer", id="extensao-docx"),
    pytest.param("extrato", b"Data;Historico;Valor\n", id="sem-extensao"),
    pytest.param("extrato.ofx", b"", id="vazio"),
    pytest.param("extrato.csv", b"x" * (TAMANHO_MAXIMO + 1), id="maior-que-o-limite"),
    pytest.param("extrato.csv", b"Data;Historico\n01/01/2026;x\n", id="csv-sem-coluna-de-valor"),
    pytest.param("extrato.csv", b"\n\n\n", id="csv-sem-cabecalho"),
    pytest.param("extrato.csv", b"Data;Historico;Valor\n32/13/2026;x;1,00\n", id="csv-data-invalida"),
    pytest.param("extrato.ofx", b"<OFX><STMTTRN><DTPOSTED>xx", id="ofx-corrompido"),
    pytest.param("extrato.ofx", b"<OFX></OFX>", id="ofx-sem-transacoes"),
    pytest.param("extrato.xlsx", b"isto nao e um zip", id="xlsx-falso"),
    pytest.param("extrato.pdf", b"isto nao e um pdf", id="pdf-falso"),
    pytest.param("extrato.csv", "Data;Histórico;Valor\n".encode(), id="csv-so-cabecalho"),
]


@pytest.mark.parametrize("nome, conteudo", INVALIDOS)
def test_c3_arquivo_invalido_nao_deixa_rastro(motor, empresa, nome, conteudo):
    lotes_antes = _lotes(motor)
    rel = processar_importacao(motor, empresa, nome, conteudo)
    _recusado(rel)
    assert _arquivos(empresa) == []
    assert _lotes(motor) == lotes_antes
    assert motor.listar() == []


def test_c3_invalido_depois_de_valido_nao_mexe_no_que_ja_existe(motor, empresa):
    processar_importacao(motor, empresa, OFX.name, OFX.read_bytes())
    arquivos, lotes, itens = _arquivos(empresa), _lotes(motor), motor.listar()
    _recusado(processar_importacao(motor, empresa, "ruim.xlsx", b"nao zip"))
    assert _arquivos(empresa) == arquivos and _lotes(motor) == lotes and motor.listar() == itens


def test_c3_csv_latin1_com_acento_e_lido(motor, empresa):
    # Comportamento real: o leitor tenta utf-8-sig e cai para cp1252; latin-1 com acento é aceito
    # e o acento é preservado. A mensagem de codificação só aparece para UnicodeDecodeError.
    conteudo = "Data;Histórico;Valor\n02/12/2026;COMPRA AÇÃO PÃO;-10,00\n".encode("latin-1")
    with pytest.raises(UnicodeDecodeError):
        conteudo.decode("utf-8")
    rel = processar_importacao(motor, empresa, "latin1.csv", conteudo)
    assert rel.ok and rel.novas == 1
    assert "AÇÃO PÃO" in motor.listar()[0]["historico_banco"]


def test_c3_mensagem_de_codificacao_para_unicode_decode_error():
    erro = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    rel = traduzir_erro("x.csv", erro)
    _recusado(rel)
    assert "codificação" in rel.detalhe and "UTF-8" in rel.o_que_fazer


@pytest.mark.parametrize("nome", ["../../x.ofx", "..\\..\\x.ofx", "/etc/x.ofx"])
def test_c3_nome_com_caminho_e_gravado_so_pelo_nome(tmp_path, motor, empresa, nome):
    rel = processar_importacao(motor, empresa, nome, OFX.read_bytes())
    assert rel.ok
    gravados = _arquivos(empresa)
    assert len(gravados) == 1 and gravados[0].name.endswith("_x.ofx")
    assert empresa.pasta_arquivos in gravados[0].parents
    # nada escrito fora da pasta de arquivos da empresa
    assert not list(tmp_path.rglob("x.ofx"))
    assert ".." not in rel.detalhe


# ---------------------------------------------------------------- C4
def test_c4_csv_sem_coluna_menciona_cabecalho(motor, empresa):
    rel = processar_importacao(motor, empresa, "a.csv", b"Data;Historico\n01/01/2026;x\n")
    assert "cabeçalho" in rel.o_que_fazer
    rel = processar_importacao(motor, empresa, "b.csv", b"\n\n")
    assert "cabeçalho" in rel.o_que_fazer


def test_c4_ofx_menciona_ofx_e_internet_banking(motor, empresa):
    for conteudo in (b"<OFX></OFX>", b"<OFX><STMTTRN><DTPOSTED>xx"):
        rel = processar_importacao(motor, empresa, "a.ofx", conteudo)
        assert "OFX" in rel.o_que_fazer and "internet banking" in rel.o_que_fazer


def test_c4_xlsx_menciona_xlsx(motor, empresa):
    rel = processar_importacao(motor, empresa, "a.xlsx", b"nao zip")
    assert ".xlsx" in rel.o_que_fazer
    assert ".xlsx" in traduzir_erro("a.xlsx", ValueError("x")).o_que_fazer


def test_c4_tamanho_menciona_periodos_menores_e_virgula_decimal():
    rel = validar_envio("grande.ofx", b"x" * (TAMANHO_MAXIMO + 1))
    assert rel is not None
    assert "períodos menores" in rel.o_que_fazer
    assert "20,0 MB" in rel.detalhe and "." not in rel.detalhe.split("tem ")[1].split(" MB")[0]
    assert "limite é 20 MB" in rel.detalhe
    assert validar_envio("no_limite.ofx", b"x" * TAMANHO_MAXIMO) is None  # exatamente 20 MB passa


def test_c4_extensao_lista_os_formatos_aceitos():
    rel = validar_envio("extrato.docx", b"x")
    assert rel is not None and ".docx" in rel.detalhe
    for extensao in EXTENSOES_ACEITAS:
        assert extensao in rel.o_que_fazer
    assert "sem extensão" in validar_envio("extrato", b"x").detalhe


# ---------------------------------------------------------------- C5
@pytest.mark.parametrize("valor, esperado", [
    (Decimal("1234.56"), "R$ 1.234,56"),
    (Decimal("-300"), "-R$ 300,00"),
    (Decimal("0"), "R$ 0,00"),
    (Decimal("1234567.5"), "R$ 1.234.567,50"),
    (Decimal("-1234.56"), "-R$ 1.234,56"),
    (Decimal("0.99"), "R$ 0,99"),
])
def test_c5_formatar_moeda(valor, esperado):
    assert formatar_moeda(valor) == esperado


def test_c5_arredondamento_meio_para_cima_sem_passar_por_float():
    # Comportamento real: ROUND_HALF_UP (meio centavo afasta-se do zero), também para negativos.
    # 0.005 e 0.015 em float seriam 0.01 e 0.01 (erro binário); em Decimal ficam 0.01 e 0.02.
    assert formatar_moeda(Decimal("0.005")) == "R$ 0,01"
    assert formatar_moeda(Decimal("0.015")) == "R$ 0,02"
    assert formatar_moeda(Decimal("1234.565")) == "R$ 1.234,57"
    assert formatar_moeda(Decimal("-0.005")) == "-R$ 0,01"
    assert formatar_moeda(Decimal("0.004")) == "R$ 0,00"
    assert formatar_moeda(Decimal("-0.004")) == "R$ 0,00"  # sem "-R$ 0,00"
    assert formatar_moeda(Decimal("12345678901234567890.12")) == "R$ 12.345.678.901.234.567.890,12"


# ---------------------------------------------------------------- C6
LINHA_FORTES = re.compile(r"^\d\d/\d\d/\d{4};\d+;\d+;\d+,\d\d;[ -:<-~]{1,118};;;;$")


def test_c6_exportacao_do_fortes_apos_importar_pela_tela(tmp_path, motor, empresa):
    rel = processar_importacao(motor, empresa, OFX.name, OFX.read_bytes())
    assert rel.ok and rel.liberados >= 1
    destino = tmp_path / "fortes.csv"
    lote, quantidade = motor.exportar(destino, ExportadorFortes(motor.plano, empresa.prefixo_marca))
    assert lote is not None and quantidade == rel.liberados
    bruto = destino.read_bytes()
    assert all(b < 128 for b in bruto)
    assert bruto.endswith(b"\r\n") and b"\n" not in bruto.replace(b"\r\n", b"")
    linhas = bruto.decode("ascii").split("\r\n")
    assert linhas[-1] == "" and len(linhas) - 1 == quantidade
    for linha in linhas[:-1]:
        assert LINHA_FORTES.match(linha), linha
        assert len(linha.split(";")) == 9
        assert f"[{empresa.prefixo_marca}-202611-" in linha
    # o que saiu é só o que estava liberado, e agora está exportado
    assert sum(1 for i in motor.listar() if i["status"] == Status.EXPORTADO.value) == quantidade


# ---------------------------------------------------------------- C7 (interface)
def _app(monkeypatch, tmp_path, *, com_empresa: bool, relatorio: RelatorioImportacao | None = None):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    dados = tmp_path / "dados"
    monkeypatch.setenv("MOTOR_CONTABIL_DADOS", str(dados))
    monkeypatch.chdir(tmp_path)
    if com_empresa:
        _cadastrar(dados)
    at = AppTest.from_file(str(APP), default_timeout=60)
    if relatorio is not None:
        at.session_state["relatorio_importacao_alfa"] = relatorio
    at.run()
    return at


def _textos(elementos) -> list[str]:
    return [e.value for e in elementos]


def test_c7a_sem_empresa_pede_cadastro(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, com_empresa=False)
    assert not at.exception
    assert any("Cadastre a primeira empresa na barra lateral" in t for t in _textos(at.info))


def test_c7b_relatorio_de_sucesso_na_tela(monkeypatch, tmp_path):
    relatorio = RelatorioImportacao(
        ok=True, titulo="Extrato importado", detalhe="Foram lidas 5 transações de x.ofx.",
        o_que_fazer="Revise os lançamentos pendentes na seção 2 antes de exportar.",
        lidas=5, novas=4, ja_importadas=1, liberados=2, pendentes=1, bloqueados=1,
        total_entradas=Decimal("3500.00"), total_saidas=Decimal("-3245.00"),
        primeira_data=date(2026, 11, 5), ultima_data=date(2026, 11, 7),
        avisos=["1 lançamento(s) pendente(s): revise na seção 2."], lote_id=7,
    )
    at = _app(monkeypatch, tmp_path, com_empresa=True, relatorio=relatorio)
    assert not at.exception
    assert _textos(at.success) == ["Extrato importado"]
    assert not at.error
    # as oito primeiras métricas da tela são as do relatório (a seção 2 vem depois)
    metricas = [(m.label, m.value) for m in at.metric][:8]
    assert metricas[:6] == [("Lidas", "5"), ("Novas", "4"), ("Já importadas", "1"),
                            ("Liberados", "2"), ("Pendentes", "1"), ("Bloqueados", "1")]
    assert metricas[6] == ("Entradas no arquivo", "R$ 3.500,00")
    assert metricas[7] == ("Saídas no arquivo", "-R$ 3.245,00")
    assert any("05/11/2026" in t and "07/11/2026" in t for t in _textos(at.markdown))
    assert any("Atenção: 1 lançamento(s) pendente(s)" in t for t in _textos(at.warning))
    assert any(t.startswith("O que fazer:") for t in _textos(at.info))


def test_c7c_relatorio_de_erro_na_tela(monkeypatch, tmp_path):
    relatorio = validar_envio("extrato.docx", b"x")
    assert relatorio is not None
    at = _app(monkeypatch, tmp_path, com_empresa=True, relatorio=relatorio)
    assert not at.exception
    assert not at.success
    assert len(at.error) == 1 and "Arquivo não importado" in at.error[0].value
    assert relatorio.detalhe in at.error[0].value
    assert any(t.startswith("O que fazer:") for t in _textos(at.info))


def test_c7d_empresa_sem_relatorio_nao_mostra_resultado(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, com_empresa=True)
    assert not at.exception
    assert not at.success and not at.error
    assert not any(t.startswith("O que fazer:") for t in _textos(at.info))
