"""Indexação (trechos + embeddings) e recuperação dos trechos mais relevantes."""
import sqlite3
from dataclasses import dataclass

import numpy as np

from . import repo
from .chunking import chunk_pages
from .embeddings import Embedder, normalize

DOC_TYPES = ("conteudo", "referencia", "material")


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: str
    document_name: str
    page_number: int | None
    text: str
    score: float


def index_document(conn: sqlite3.Connection, embedder: Embedder, document_id: str) -> int:
    """(Re)indexa um documento. Tudo ou nada: se o embedding falhar, nada é gravado."""
    doc = conn.execute("SELECT id, notebook_id FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not doc:
        raise ValueError("Documento não encontrado.")
    pages = [(p["page_number"], p["text"]) for p in repo.get_pages(conn, document_id)]
    chunks = chunk_pages(pages)
    vectors = embedder.embed_documents([c.text for c in chunks])  # pode levantar EmbeddingError
    if len(chunks) != len(vectors):
        raise ValueError("Número de vetores diferente do número de trechos.")
    with conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.executemany(
            """INSERT INTO chunks (document_id, notebook_id, chunk_index, page_number, text, embedding,
                   embedding_model, dim) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (document_id, doc["notebook_id"], i, c.page_number, c.text,
                 np.asarray(v, dtype=np.float32).tobytes(), embedder.model, embedder.dim)
                for i, (c, v) in enumerate(zip(chunks, vectors))
            ],
        )
        conn.execute(
            "UPDATE documents SET indexed_model = ?, indexed_at = ? WHERE id = ?",
            (embedder.model, repo.now(), document_id),
        )
    return len(chunks)


def pending_documents(conn: sqlite3.Connection, notebook_id: str, embedder: Embedder) -> list[sqlite3.Row]:
    """Documentos sem índice ou indexados com outro modelo/dimensão."""
    return conn.execute(
        """SELECT d.* FROM documents d WHERE d.notebook_id = ?
             AND (d.indexed_model IS NULL OR d.indexed_model != ?
                  OR EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id AND c.dim != ?))
           ORDER BY d.added_at""",
        (notebook_id, embedder.model, embedder.dim),
    ).fetchall()


def index_pending(conn: sqlite3.Connection, embedder: Embedder, notebook_id: str) -> dict[str, int | str]:
    """Indexa o que falta. Devolve {nome do documento: nº de trechos ou mensagem de erro}."""
    from .embeddings import EmbeddingError

    results: dict[str, int | str] = {}
    for doc in pending_documents(conn, notebook_id, embedder):
        try:
            results[doc["name"]] = index_document(conn, embedder, doc["id"])
        except EmbeddingError as exc:
            results[doc["name"]] = str(exc)
    return results


def search(
    conn: sqlite3.Connection,
    embedder: Embedder,
    notebook_id: str,
    query: str,
    top_k: int = 6,
    document_ids: list[str] | None = None,
    doc_types: tuple[str, ...] = ("conteudo",),
) -> list[Hit]:
    """Trechos mais parecidos com a pergunta, só do notebook indicado e do modelo atual."""
    if not query.strip() or top_k < 1:
        return []
    sql = """SELECT c.id, c.document_id, d.name, c.page_number, c.text, c.embedding
             FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE c.notebook_id = ? AND c.embedding_model = ? AND c.dim = ?"""
    params: list = [notebook_id, embedder.model, embedder.dim]
    if doc_types:
        sql += f" AND d.doc_type IN ({','.join('?' * len(doc_types))})"
        params += list(doc_types)
    if document_ids is not None:
        if not document_ids:
            return []
        sql += f" AND c.document_id IN ({','.join('?' * len(document_ids))})"
        params += list(document_ids)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []
    matrix = normalize(np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]))
    scores = matrix @ normalize(embedder.embed_query(query))[0]
    order = np.argsort(-scores, kind="stable")[:top_k]
    return [
        Hit(rows[i]["id"], rows[i]["document_id"], rows[i]["name"], rows[i]["page_number"], rows[i]["text"], float(scores[i]))
        for i in order
    ]


def chunk_count(conn: sqlite3.Connection, document_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)).fetchone()[0]
