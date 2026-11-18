"""Gravação padronizada no audit_log da empresa e na auditoria de acesso central."""

from __future__ import annotations

import json
import sqlite3

from storage.database import agora


def registrar(con: sqlite3.Connection, usuario: str, acao: str, entidade: str,
              entidade_id=None, **detalhes) -> None:
    con.execute(
        "INSERT INTO audit_log (ts, usuario, acao, entidade, entidade_id, detalhes) VALUES (?, ?, ?, ?, ?, ?)",
        (agora(), usuario, acao, entidade, None if entidade_id is None else str(entidade_id),
         json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes else None),
    )


def registrar_acesso(central: sqlite3.Connection, usuario_id, empresa_id, acao: str,
                     resultado: str, **detalhes) -> None:
    central.execute(
        "INSERT INTO audit_acesso (ts, usuario_id, empresa_id, acao, resultado, detalhes) VALUES (?, ?, ?, ?, ?, ?)",
        (agora(), usuario_id, empresa_id, acao, resultado,
         json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes else None),
    )


def listar(con: sqlite3.Connection, limite: int = 200) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
