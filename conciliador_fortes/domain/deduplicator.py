"""Checagem de duplicidade em três níveis, sem nunca excluir nada sozinho.

1. Arquivo: mesmo SHA-256 de um arquivo já carregado -> carga bloqueada.
2. FITID (OFX): mesmo identificador na mesma conta -> alerta pendente.
3. Semelhança: mesma data, mesmo valor e histórico parecido vindo de outro
   arquivo -> alerta pendente.

Alerta pendente vai para a fila de decisão; a pessoa decide manter ou descartar.
"""

from __future__ import annotations

import hashlib
import sqlite3
from difflib import SequenceMatcher

import config
from parsers.comum import normalizar


def sha256(bruto: bytes) -> str:
    return hashlib.sha256(bruto).hexdigest()


def arquivo_repetido(con: sqlite3.Connection, hash_hex: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM arquivos WHERE sha256 = ? AND status = 'carregado' ORDER BY id LIMIT 1", (hash_hex,)
    ).fetchone()


def semelhanca(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def procurar(con: sqlite3.Connection, mov: dict, conta_banco: str, arquivo_id: int) -> tuple[int, str] | None:
    """Devolve (id do movimento existente, motivo) ou None."""
    if mov.get("fitid"):
        r = con.execute(
            "SELECT id FROM movimentos WHERE conta_banco = ? AND fitid = ? AND status <> 'descartado' "
            "AND arquivo_id <> ? ORDER BY id LIMIT 1",
            (conta_banco, mov["fitid"], arquivo_id),
        ).fetchone()
        if r:
            return r["id"], f"FITID {mov['fitid']} já carregado"
    candidatos = con.execute(
        "SELECT id, historico FROM movimentos WHERE conta_banco = ? AND data = ? AND valor_centavos = ? "
        "AND arquivo_id <> ? AND status <> 'descartado'",
        (conta_banco, mov["data"], mov["valor_centavos"], arquivo_id),
    ).fetchall()
    melhor = max(candidatos, key=lambda c: semelhanca(c["historico"], mov["historico"]), default=None)
    if melhor is not None:
        s = semelhanca(melhor["historico"], mov["historico"])
        if s >= config.LIMIAR_SEMELHANCA:
            return melhor["id"], f"mesma data e valor, histórico {s:.0%} parecido"
    return None
