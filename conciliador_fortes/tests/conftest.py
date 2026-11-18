from __future__ import annotations

from pathlib import Path

import pytest

from domain.operacoes import Contexto
from storage import usuarios
from storage.database import conectar_central

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"


@pytest.fixture
def ambiente(tmp_path):
    """Central com duas empresas e três usuários: operador, revisor e alguém de outra empresa."""
    data = tmp_path / "data"
    central = conectar_central(data)
    e1 = usuarios.criar_empresa(central, "alfa", "Alfa Servicos Ltda", "11.111.111/0001-11", data_dir=data)
    e2 = usuarios.criar_empresa(central, "beta", "Beta Comercio Ltda", "22.222.222/0001-22", data_dir=data)
    op = usuarios.criar_usuario(central, "Operadora A", "op@exemplo.test", "senha-forte-1", "equipe")
    rev = usuarios.criar_usuario(central, "Revisor B", "rev@exemplo.test", "senha-forte-2", "revisor")
    fora = usuarios.criar_usuario(central, "Pessoa C", "c@exemplo.test", "senha-forte-3", "equipe")
    usuarios.conceder(central, op, e1, "operador")
    usuarios.conceder(central, rev, e1, "aprovador")
    usuarios.conceder(central, fora, e2, "aprovador")

    def ctx(email, slug="alfa"):
        u = central.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        return Contexto.abrir(central, u, slug, data)

    yield {"central": central, "data": data, "ctx": ctx}
    central.close()


@pytest.fixture
def op(ambiente):
    return ambiente["ctx"]("op@exemplo.test")


@pytest.fixture
def rev(ambiente):
    return ambiente["ctx"]("rev@exemplo.test")


@pytest.fixture
def empresa_pronta(op, rev):
    """Plano, regras e sócio cadastrados na empresa alfa."""
    from domain import operacoes as o
    o.carregar_plano(op, "plano.csv", (EXEMPLOS / "plano_contas_fortes.csv").read_bytes())
    o.importar_regras_json(op, (EXEMPLOS / "regras_exemplo.json").read_bytes())
    o.adicionar_socio(op, "SOCIO EXEMPLO")
    o.definir_prefixo(op, "ALF")
    return op, rev
