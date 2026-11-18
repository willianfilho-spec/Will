"""Cria um ambiente de demonstração com dados sintéticos.

    CONCILIADOR_DATA_DIR=/tmp/demo python scripts/seed_demo.py

Usuários (senha: demo-1234): admin@demo.test, operador@demo.test, revisor@demo.test.
Não use em produção.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
from domain import operacoes as o  # noqa: E402
from storage import usuarios  # noqa: E402
from storage.database import conectar_central  # noqa: E402

EX = RAIZ / "exemplos"

if (config.DATA_DIR / "central.db").exists():
    sys.exit(f"{config.DATA_DIR} já tem dados; use outra pasta em CONCILIADOR_DATA_DIR.")
central = conectar_central()
emp = usuarios.criar_empresa(central, "demo", "Empresa Demonstracao Ltda", "00.000.000/0001-91")
adm = usuarios.criar_usuario(central, "Admin Demo", "admin@demo.test", "demo-1234", "admin")
op = usuarios.criar_usuario(central, "Operadora Demo", "operador@demo.test", "demo-1234", "equipe")
rev = usuarios.criar_usuario(central, "Revisor Demo", "revisor@demo.test", "demo-1234", "revisor")
usuarios.conceder(central, op, emp, "operador")
usuarios.conceder(central, rev, emp, "revisor")
u = central.execute("SELECT * FROM usuarios WHERE id = ?", (op,)).fetchone()
ctx = o.Contexto.abrir(central, u, "demo")
o.carregar_plano(ctx, "plano_contas_fortes.csv", (EX / "plano_contas_fortes.csv").read_bytes())
o.definir_conta_banco_padrao(ctx, "362")
o.definir_prefixo(ctx, "DEMO")
o.importar_regras_json(ctx, (EX / "regras_exemplo.json").read_bytes())
o.adicionar_socio(ctx, "SOCIO EXEMPLO")
o.carregar_razao(ctx, "razao_abertura.csv", b"31/08/2026;362;90;10000,00;SALDO DE ABERTURA;;;;\r\n")
o.carregar_extrato(ctx, "extrato_exemplo.ofx", (EX / "extrato_exemplo.ofx").read_bytes(), "362")
o.informar_saldos(ctx, "2026-09", "362", 1_000_000, 91_115)
print(f"Demonstração criada em {config.DATA_DIR}")
