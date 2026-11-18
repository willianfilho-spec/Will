"""Cria o primeiro administrador (ou mais um). Pede a senha sem mostrá-la.

    python scripts/criar_admin.py

A senha segue a política do sistema (10+ caracteres, 3 tipos). No primeiro acesso a pessoa será levada
a ativar o 2FA. Prefira rodar isto no servidor, não por rede.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage import usuarios  # noqa: E402
from storage.database import conectar_central  # noqa: E402
from web import seguranca as sg  # noqa: E402

nome = input("Nome: ").strip()
email = input("E-mail (login): ").strip().lower()
senha = getpass.getpass("Senha: ")
if senha != getpass.getpass("Repita a senha: "):
    sys.exit("As senhas não conferem.")
try:
    sg.validar_politica_senha(senha, email, nome)
except ValueError as exc:
    sys.exit(str(exc))
central = conectar_central()
try:
    usuarios.criar_usuario(central, nome, email, senha, "admin")
except Exception as exc:  # noqa: BLE001
    sys.exit(f"Não foi possível criar: {exc}")
print(f"Administrador {email} criado. No primeiro acesso, ative o 2FA.")
