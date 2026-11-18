"""Dados de demonstração do web app (importado por rodar_web.py --demo). Só dados inventados."""

from __future__ import annotations

from pathlib import Path

from domain import operacoes as o
from storage import usuarios
from storage.database import conectar_central

EX = Path(__file__).resolve().parent.parent / "exemplos"
SENHA = "Demo-Conciliador-2026!"


def criar_demo(data_dir: Path) -> None:
    c = conectar_central(data_dir)
    emp = usuarios.criar_empresa(c, "demo", "Empresa Demonstracao Ltda", "00.000.000/0001-91", data_dir=data_dir)
    ids = {}
    for nome, email, papel, pe in (("Admin Demo", "admin@demo.test", "admin", None),
                                   ("Operadora Demo", "operador@demo.test", "equipe", "operador"),
                                   ("Revisor Demo", "revisor@demo.test", "revisor", "revisor"),
                                   ("Cliente Demo", "cliente@demo.test", "cliente", "cliente")):
        ids[email] = usuarios.criar_usuario(c, nome, email, SENHA, papel)
        if pe:
            usuarios.conceder(c, ids[email], emp, pe)
    u = c.execute("SELECT * FROM usuarios WHERE email = 'operador@demo.test'").fetchone()
    ctx = o.Contexto.abrir(c, u, "demo", data_dir)
    o.carregar_plano(ctx, "plano_contas_fortes.csv", (EX / "plano_contas_fortes.csv").read_bytes())
    o.definir_conta_banco_padrao(ctx, "362")
    o.definir_prefixo(ctx, "DEMO")
    o.importar_regras_json(ctx, (EX / "regras_exemplo.json").read_bytes())
    o.adicionar_socio(ctx, "SOCIO EXEMPLO")
    o.carregar_razao(ctx, "razao_abertura.csv", b"31/08/2026;362;90;10000,00;SALDO DE ABERTURA;;;;\r\n")
    o.carregar_extrato(ctx, "extrato_exemplo.ofx", (EX / "extrato_exemplo.ofx").read_bytes(), "362")
    o.informar_saldos(ctx, "2026-09", "362", 1_000_000, 91_115)
    ctx.con.close()
    c.close()
