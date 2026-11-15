from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from motor_contabil import backup, empresas
from motor_contabil.cli import main as cli

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"
PLANO = EXEMPLOS / "plano_contas.csv"
REGRAS = EXEMPLOS / "regras.json"
OFX = EXEMPLOS / "extrato_exemplo.ofx"


def cadastrar(dados, ident="alfa", cnpj="11.111.111/0001-11", prefixo="AL", **mudancas):
    args = dict(nome=f"Empresa {ident}", cnpj=cnpj, conta_bancaria="BANCO_1", prefixo_marca=prefixo,
                formato_plano="motor", plano=PLANO, regras=REGRAS) | mudancas
    return empresas.cadastrar(dados, ident, **args)


def test_cadastro_cria_pasta_completa(tmp_path):
    e = cadastrar(tmp_path)
    assert {p.name for p in e.pasta.iterdir()} == {"empresa.json", "plano.csv", "regras.json", "arquivos"}
    assert empresas.listar(tmp_path)[0].nome == "Empresa alfa"
    assert empresas.abrir(tmp_path, "alfa").prefixo_marca == "AL"


@pytest.mark.parametrize("ident", ["../fora", "A", "a", "com espaço", "x/y", ".oculta", ""])
def test_identificador_invalido(tmp_path, ident):
    with pytest.raises(ValueError, match="identificador inválido"):
        cadastrar(tmp_path, ident)
    assert not any(tmp_path.parent.glob("fora"))


@pytest.mark.parametrize("mudancas, trecho", [
    ({"cnpj": "123"}, "14 dígitos"),
    ({"prefixo_marca": "nx"}, "prefixo"),
    ({"nome": " "}, "nome"),
    ({"conta_bancaria": ""}, "conta bancária"),
    ({"formato_plano": "outro"}, "formato"),
])
def test_cadastro_com_dado_invalido(tmp_path, mudancas, trecho):
    with pytest.raises(ValueError, match=trecho):
        cadastrar(tmp_path, **mudancas)
    assert empresas.listar(tmp_path) == []


def test_regras_com_conta_fora_do_plano_sao_recusadas(tmp_path):
    regras = json.loads(REGRAS.read_text(encoding="utf-8"))
    regras["regras"][0]["conta"] = "9.9.9.99"
    arquivo = tmp_path / "regras_ruins.json"
    arquivo.write_text(json.dumps(regras), encoding="utf-8")
    with pytest.raises(ValueError, match="não combinam"):
        cadastrar(tmp_path / "dados", regras=arquivo)
    assert empresas.listar(tmp_path / "dados") == []


def test_cnpj_e_prefixo_nao_se_repetem(tmp_path):
    cadastrar(tmp_path)
    with pytest.raises(ValueError, match="CNPJ já está cadastrado"):
        cadastrar(tmp_path, "beta", cnpj="11111111000111", prefixo="BE")
    with pytest.raises(ValueError, match="prefixo AL já é usado"):
        cadastrar(tmp_path, "beta", cnpj="22.222.222/0001-22", prefixo="AL")
    with pytest.raises(ValueError, match="já existe a pasta"):
        cadastrar(tmp_path, "alfa", cnpj="33.333.333/0001-33", prefixo="XX")


def test_empresas_nao_enxergam_dados_uma_da_outra(tmp_path):
    a = cadastrar(tmp_path)
    b = cadastrar(tmp_path, "beta", cnpj="22.222.222/0001-22", prefixo="BE")
    motor_a = a.abrir_motor("ana")
    motor_a.importar(OFX)
    n = len(motor_a.listar())
    motor_a.banco.fechar()
    motor_b = b.abrir_motor("bia")
    assert n > 0 and motor_b.listar() == []
    assert motor_b.importar(OFX).novas == n  # cada empresa tem o seu controle de duplicidade
    motor_b.banco.fechar()
    assert a.caminho_banco != b.caminho_banco


def test_original_guardado_uma_vez_e_aviso_de_empresa_errada(tmp_path):
    a = cadastrar(tmp_path)
    b = cadastrar(tmp_path, "beta", cnpj="22.222.222/0001-22", prefixo="BE")
    conteudo = OFX.read_bytes()
    caminho, repetido = empresas.guardar_original(a, "../../extrato.ofx", conteudo)
    assert not repetido and a.pasta_arquivos in caminho.parents and caminho.read_bytes() == conteudo
    assert empresas.guardar_original(a, "outro_nome.ofx", conteudo) == (caminho, True)
    assert empresas.empresas_com_o_arquivo(tmp_path, conteudo, exceto="beta") == ["alfa"]
    assert empresas.empresas_com_o_arquivo(tmp_path, conteudo, exceto="alfa") == []
    assert list(b.pasta_arquivos.rglob("*")) == []


def test_configuracao_adulterada_e_recusada(tmp_path):
    a = cadastrar(tmp_path)
    config = json.loads((a.pasta / "empresa.json").read_text(encoding="utf-8"))
    config["identificador"] = "beta"
    (a.pasta / "empresa.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="não corresponde à pasta"):
        empresas.listar(tmp_path)


def test_cli_com_empresa(tmp_path, capsys):
    dados = str(tmp_path / "dados")
    assert cli(["--dados", dados, "cadastrar-empresa", "alfa", "--nome", "Alfa", "--cnpj",
                "11.111.111/0001-11", "--conta", "BANCO_1", "--prefixo", "AL", "--formato-plano",
                "motor", "--plano", str(PLANO), "--regras", str(REGRAS)]) == 0
    assert cli(["--dados", dados, "--empresa", "alfa", "importar", str(OFX)]) == 0
    assert "novas" in capsys.readouterr().out
    assert cli(["--dados", dados, "--empresa", "alfa", "exportar", str(tmp_path / "lote.csv")]) == 0
    linhas = (tmp_path / "lote.csv").read_bytes().decode("ascii").split("\r\n")[:-1]
    assert linhas and all("[AL-" in l and l.endswith(";;;;") for l in linhas)
    assert any(Path(dados, "alfa", "arquivos").rglob("*_extrato_exemplo.ofx"))
    assert cli(["--dados", dados, "--empresa", "nao-existe", "listar"]) == 1


def test_backup_da_pasta_de_dados_leva_todas_as_empresas(tmp_path):
    dados = tmp_path / "dados"
    a = cadastrar(dados)
    cadastrar(dados, "beta", cnpj="22.222.222/0001-22", prefixo="BE")
    m = a.abrir_motor("ana")
    m.importar(OFX)
    m.banco.fechar()
    copia = backup.fazer(dados, tmp_path / "bkp")
    backup.restaurar(copia.pasta, tmp_path / "restaurado")
    assert [e.identificador for e in empresas.listar(tmp_path / "restaurado")] == ["alfa", "beta"]
    con = sqlite3.connect(tmp_path / "restaurado" / "alfa" / "motor.db")
    assert con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0] > 0
    con.close()
