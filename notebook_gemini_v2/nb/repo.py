"""Acesso a dados dos notebooks, documentos e mensagens."""
import sqlite3
import uuid
from datetime import datetime


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_notebook(conn: sqlite3.Connection, name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Informe um nome para o notebook.")
    nid = str(uuid.uuid4())
    conn.execute("INSERT INTO notebooks (id, name, created_at) VALUES (?, ?, ?)", (nid, name[:200], now()))
    conn.commit()
    return nid


def list_notebooks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, name, created_at FROM notebooks ORDER BY created_at DESC, rowid DESC").fetchall()


def list_documents(conn: sqlite3.Connection, notebook_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM documents WHERE notebook_id = ? ORDER BY added_at DESC, rowid DESC", (notebook_id,)
    ).fetchall()


def get_pages(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT page_number, text, char_count FROM pages WHERE document_id = ? ORDER BY id", (document_id,)
    ).fetchall()


def add_message(conn: sqlite3.Connection, notebook_id: str, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO messages (notebook_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (notebook_id, role, content, now()),
    )
    conn.commit()


def list_messages(conn: sqlite3.Connection, notebook_id: str, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT role, content, created_at FROM messages WHERE notebook_id = ? ORDER BY id DESC LIMIT ?",
        (notebook_id, limit),
    ).fetchall()


def find_notebook_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, name, created_at FROM notebooks WHERE name = ? ORDER BY rowid LIMIT 1", (name.strip(),)
    ).fetchone()
