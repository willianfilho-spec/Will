"""Auditoria encadeada: cada linha guarda o hash da anterior.

Apagar, trocar ou inserir uma linha por fora do app quebra a cadeia, e
`verificar_cadeia` aponta onde. Os triggers do banco já impedem alteração
pelo app; a cadeia detecta quem mexeu no arquivo .db diretamente.
Limite honesto: quem controla o arquivo inteiro pode refazer a cadeia toda.
Para isso, o hash final é gravado no manifesto de cada backup.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from storage.database import agora

GENESE = "0" * 64
CAMPOS = {
    "audit_log": ("ts", "usuario", "acao", "entidade", "entidade_id", "detalhes"),
    "audit_acesso": ("ts", "usuario_id", "empresa_id", "acao", "resultado", "detalhes"),
}


def _hash(anterior: str, campos: dict) -> str:
    corpo = json.dumps(campos, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256((anterior + corpo).encode("utf-8")).hexdigest()


def _inserir(con: sqlite3.Connection, tabela: str, campos: dict) -> None:
    proprio = not con.in_transaction
    if proprio:
        con.execute("BEGIN IMMEDIATE")
    try:
        ult = con.execute(f"SELECT hash FROM {tabela} WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        anterior = ult["hash"] if ult else GENESE
        nomes = list(campos) + ["hash_anterior", "hash"]
        con.execute(f"INSERT INTO {tabela} ({', '.join(nomes)}) VALUES ({', '.join('?' * len(nomes))})",
                    [*campos.values(), anterior, _hash(anterior, campos)])
    except BaseException:
        if proprio:
            con.execute("ROLLBACK")
        raise
    if proprio:
        con.execute("COMMIT")


def registrar(con: sqlite3.Connection, usuario: str, acao: str, entidade: str,
              entidade_id=None, **detalhes) -> None:
    _inserir(con, "audit_log", {
        "ts": agora(), "usuario": usuario, "acao": acao, "entidade": entidade,
        "entidade_id": None if entidade_id is None else str(entidade_id),
        "detalhes": json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes else None,
    })


def registrar_acesso(central: sqlite3.Connection, usuario_id, empresa_id, acao: str,
                     resultado: str, **detalhes) -> None:
    _inserir(central, "audit_acesso", {
        "ts": agora(), "usuario_id": usuario_id, "empresa_id": empresa_id, "acao": acao, "resultado": resultado,
        "detalhes": json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes else None,
    })


def listar(con: sqlite3.Connection, limite: int = 200) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limite,)).fetchall()


def hash_final(con: sqlite3.Connection, tabela: str = "audit_log") -> str:
    r = con.execute(f"SELECT hash FROM {tabela} WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    return r["hash"] if r else GENESE


def verificar_cadeia(con: sqlite3.Connection, tabela: str = "audit_log") -> list[str]:
    """Problemas da cadeia (vazio = íntegra). Linhas antigas sem hash são ignoradas."""
    problemas: list[str] = []
    anterior, id_ant, viu_hash = GENESE, None, False
    for r in con.execute(f"SELECT * FROM {tabela} ORDER BY id"):
        if r["hash"] is None:
            if viu_hash:
                problemas.append(f"{tabela} linha {r['id']}: sem hash depois de a cadeia começar (inserida por fora?)")
            continue
        if viu_hash and id_ant is not None and r["id"] != id_ant + 1:
            problemas.append(f"{tabela}: linhas {id_ant + 1} a {r['id'] - 1} ausentes (apagadas?)")
        if r["hash_anterior"] != anterior:
            problemas.append(f"{tabela} linha {r['id']}: encadeamento quebrado")
        esperado = _hash(r["hash_anterior"], {c: r[c] for c in CAMPOS[tabela]})
        if esperado != r["hash"]:
            problemas.append(f"{tabela} linha {r['id']}: conteúdo não confere com o hash (alterada?)")
        anterior, id_ant, viu_hash = r["hash"], r["id"], True
    seq = con.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (tabela,)).fetchone()
    mx = con.execute(f"SELECT COALESCE(MAX(id), 0) FROM {tabela}").fetchone()[0]
    if seq and viu_hash and seq["seq"] > mx:
        problemas.append(f"{tabela}: {seq['seq'] - mx} linha(s) finais ausentes (apagadas?)")
    return problemas
