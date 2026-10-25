"""Conexão SQLite e migrações versionadas (PRAGMA user_version)."""
import sqlite3
from datetime import datetime
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
    (
        2,
        """
        -- 'conteudo' = norma/guia que sustenta respostas; 'referencia' = lista de links/bibliografia,
        -- 'material' = peças gráficas etc. Só 'conteudo' entra na busca por padrão.
        ALTER TABLE documents ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'conteudo';
        ALTER TABLE documents ADD COLUMN indexed_model TEXT;
        ALTER TABLE documents ADD COLUMN indexed_at TEXT;
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page_number INTEGER,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL,
            embedding_model TEXT NOT NULL,
            dim INTEGER NOT NULL
        );
        CREATE INDEX idx_chunks_notebook ON chunks(notebook_id, embedding_model);
        CREATE INDEX idx_chunks_document ON chunks(document_id, chunk_index);
        """,
    ),
    (
        3,
        """
        -- JSON com os trechos recuperados e o resultado da verificação de cada citação,
        -- para auditar a resposta depois sem reexecutar o modelo.
        ALTER TABLE messages ADD COLUMN metadata TEXT;
        """,
    ),
]


def backup_legacy_database(path: Path) -> Path | None:
    """O banco da v1 usa os mesmos nomes de tabela, mas sem versão e com outra estrutura.
    Em vez de falhar ou misturar, ele é guardado ao lado como cópia e um banco novo é criado.
    Devolve o caminho da cópia, ou None se não havia banco da v1."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    probe = sqlite3.connect(path)
    try:
        version = probe.execute("PRAGMA user_version").fetchone()[0]
        has_notebooks = probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notebooks'").fetchone()
    finally:
        probe.close()
    if version != 0 or not has_notebooks:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.v1-backup-{stamp}{path.suffix}")
    path.rename(backup)
    return backup


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
