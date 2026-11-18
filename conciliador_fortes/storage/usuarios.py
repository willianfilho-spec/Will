"""Usuários, empresas e permissões (central.db).

Matriz de permissões da Etapa A. O papel vale por empresa; admin global vê tudo.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3

import config
from storage.database import agora, conectar_empresa, validar_slug

ITERACOES = 200_000

# ação -> papéis de empresa que podem executá-la
PERMISSOES = {
    "ver": {"cliente", "operador", "revisor", "aprovador"},
    "carregar": {"cliente", "operador", "revisor", "aprovador"},
    "cadastrar": {"operador", "revisor", "aprovador"},
    "classificar": {"operador", "revisor", "aprovador"},
    "decidir_duplicidade": {"operador", "revisor", "aprovador"},
    "segunda_confirmacao": {"revisor", "aprovador"},
    "conciliar": {"operador", "revisor", "aprovador"},
    "revisar_diferenca": {"revisor", "aprovador"},
    "exportar": {"aprovador", "revisor"},
    "registrar_retorno": {"operador", "revisor", "aprovador"},
    "backup": {"aprovador"},
}


class AcessoNegado(PermissionError):
    pass


def hash_senha(senha: str) -> str:
    if len(senha) < 8:
        raise ValueError("a senha precisa ter ao menos 8 caracteres")
    sal = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES)
    return f"pbkdf2_sha256${ITERACOES}${sal.hex()}${dk.hex()}"


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        _, it, sal, dk = guardado.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


def criar_usuario(central: sqlite3.Connection, nome: str, email: str, senha: str, papel_global: str) -> int:
    if papel_global not in config.PAPEIS_GLOBAIS:
        raise ValueError(f"papel global inválido: {papel_global}")
    if not nome.strip() or "@" not in email:
        raise ValueError("informe nome e e-mail válidos")
    cur = central.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, papel_global, criado_em) VALUES (?, ?, ?, ?, ?)",
        (nome.strip(), email.strip().lower(), hash_senha(senha), papel_global, agora()),
    )
    return cur.lastrowid


def autenticar(central: sqlite3.Connection, email: str, senha: str) -> sqlite3.Row | None:
    u = central.execute("SELECT * FROM usuarios WHERE email = ? AND ativo = 1",
                        (email.strip().lower(),)).fetchone()
    if u and conferir_senha(senha, u["senha_hash"]):
        return u
    return None


def criar_empresa(central: sqlite3.Connection, slug: str, razao_social: str, cnpj: str,
                  limite_centavos: int = config.LIMITE_REVISAO_PADRAO_CENTAVOS,
                  data_dir=None) -> int:
    validar_slug(slug)
    digitos = "".join(c for c in cnpj if c.isdigit())
    if len(digitos) not in (11, 14):
        raise ValueError("CNPJ/CPF deve ter 14 ou 11 dígitos")
    cur = central.execute(
        "INSERT INTO empresas (slug, razao_social, cnpj, limite_revisao_centavos) VALUES (?, ?, ?, ?)",
        (slug, razao_social.strip(), digitos, int(limite_centavos)),
    )
    conectar_empresa(slug, data_dir).close()  # cria pasta e banco isolados
    return cur.lastrowid


def conceder(central: sqlite3.Connection, usuario_id: int, empresa_id: int, papel: str) -> None:
    if papel not in config.PAPEIS_EMPRESA:
        raise ValueError(f"papel de empresa inválido: {papel}")
    central.execute(
        "INSERT INTO permissoes_empresa (usuario_id, empresa_id, papel_empresa) VALUES (?, ?, ?) "
        "ON CONFLICT(usuario_id, empresa_id) DO UPDATE SET papel_empresa = excluded.papel_empresa",
        (usuario_id, empresa_id, papel),
    )


def papel_na_empresa(central: sqlite3.Connection, usuario_id: int, empresa_id: int) -> str | None:
    u = central.execute("SELECT papel_global, ativo FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not u or not u["ativo"]:
        return None
    if u["papel_global"] == "admin":
        return "aprovador"
    p = central.execute(
        "SELECT papel_empresa FROM permissoes_empresa WHERE usuario_id = ? AND empresa_id = ?",
        (usuario_id, empresa_id),
    ).fetchone()
    return p["papel_empresa"] if p else None


def empresas_do_usuario(central: sqlite3.Connection, usuario_id: int) -> list[sqlite3.Row]:
    u = central.execute("SELECT papel_global FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if u and u["papel_global"] == "admin":
        return central.execute("SELECT * FROM empresas WHERE ativa = 1 ORDER BY razao_social").fetchall()
    return central.execute(
        "SELECT e.* FROM empresas e JOIN permissoes_empresa p ON p.empresa_id = e.id "
        "WHERE p.usuario_id = ? AND e.ativa = 1 ORDER BY e.razao_social",
        (usuario_id,),
    ).fetchall()


def pode(central: sqlite3.Connection, usuario_id: int, empresa_id: int, acao: str) -> bool:
    papel = papel_na_empresa(central, usuario_id, empresa_id)
    return papel is not None and papel in PERMISSOES.get(acao, set())


def exigir(central: sqlite3.Connection, usuario_id: int, empresa_id: int, acao: str) -> None:
    if not pode(central, usuario_id, empresa_id, acao):
        raise AcessoNegado(f"sem permissão para '{acao}' nesta empresa")


def abrir_empresa_autorizada(central: sqlite3.Connection, usuario_id: int, slug: str, data_dir=None):
    """Única porta de entrada para o banco de uma empresa: checa permissão e audita."""
    from storage.audit import registrar_acesso
    emp = central.execute("SELECT * FROM empresas WHERE slug = ? AND ativa = 1", (slug,)).fetchone()
    if emp is None or not pode(central, usuario_id, emp["id"], "ver"):
        registrar_acesso(central, usuario_id, emp["id"] if emp else None, "abrir_empresa", "negado", slug=slug)
        raise AcessoNegado("empresa inexistente ou sem permissão")
    registrar_acesso(central, usuario_id, emp["id"], "abrir_empresa", "ok")
    return emp, conectar_empresa(slug, data_dir)
