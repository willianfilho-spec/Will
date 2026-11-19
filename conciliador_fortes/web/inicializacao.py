"""Primeira execução em hospedagem sem terminal: cria o administrador a partir de variáveis de ambiente.

    CONCILIADOR_ADMIN_EMAIL       e-mail (login) do primeiro administrador
    CONCILIADOR_ADMIN_NOME        nome (opcional; padrão "Administrador")
    CONCILIADOR_ADMIN_SENHA       senha INICIAL; precisa passar na política de senha

Só age se ainda não existir nenhum usuário. A senha inicial é de uso único: a pessoa é obrigada a trocá-la no primeiro
acesso e a ativar o 2FA. Depois de criado, REMOVA a variável CONCILIADOR_ADMIN_SENHA do painel da plataforma.
"""

from __future__ import annotations

import os
from pathlib import Path

from storage import usuarios
from storage.database import conectar_central
from web import seguranca as sg


def criar_admin_inicial(data_dir: Path, env=os.environ) -> str:
    """Devolve uma mensagem curta dizendo o que foi feito (nunca inclui a senha)."""
    email, senha = env.get("CONCILIADOR_ADMIN_EMAIL", "").strip().lower(), env.get("CONCILIADOR_ADMIN_SENHA", "")
    central = conectar_central(data_dir)
    try:
        if central.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0:
            return "já existem usuários; nenhum administrador criado" + (
                " (remova CONCILIADOR_ADMIN_SENHA do ambiente)" if senha else "")
        if not email or not senha:
            return ("AVISO: não há nenhum usuário. Defina CONCILIADOR_ADMIN_EMAIL e CONCILIADOR_ADMIN_SENHA "
                    "para criar o primeiro administrador, ou rode scripts/criar_admin.py.")
        nome = env.get("CONCILIADOR_ADMIN_NOME", "Administrador").strip() or "Administrador"
        try:
            sg.validar_politica_senha(senha, email, nome)
        except ValueError as exc:
            return f"ERRO: administrador NÃO criado. {exc}"
        uid = usuarios.criar_usuario(central, nome, email, senha, "admin")
        central.execute("UPDATE usuarios SET deve_trocar_senha = 1 WHERE id = ?", (uid,))
        return f"administrador {email} criado; a senha deverá ser trocada no primeiro acesso. Remova CONCILIADOR_ADMIN_SENHA do ambiente."
    finally:
        central.close()
