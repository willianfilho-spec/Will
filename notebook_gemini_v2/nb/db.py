"""Conexão SQLite e migrações versionadas (PRAGMA user_version)."""
import sqlite3
from pathlib import Path

# Cada item é (versão, script). Nunca edite uma migração já publicada:
# acrescente uma nova.
MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE notebooks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            stored_path TEXT NOT NULL,
            paginated INTEGER NOT NULL,
            page_count INTEGER NOT NULL,
            empty_page_count INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            UNIQUE (notebook_id, sha256)
        );
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER,
            text TEXT NOT NULL,
            char_count INTEGER NOT NULL
        );
        CREATE INDEX idx_pages_document ON pages(document_id, page_number);
        CREATE INDEX idx_documents_notebook ON documents(notebook_id);
        CREATE INDEX idx_messages_notebook ON messages(notebook_id, id);
        """,
    ),
]


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    current = schema_version(conn)
    for version, script in MIGRATIONS:
        if version <= current:
            continue
        # executescript confirma a transação anterior; por isso o BEGIN explícito.
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
