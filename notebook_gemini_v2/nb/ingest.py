"""Importação de documentos: validação, duplicados, extração e gravação."""
import hashlib
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

from .config import SUPPORTED_EXTENSIONS
from .extract import ExtractionError, extract
from .repo import now


class IngestError(Exception):
    """Falha esperada de importação; a mensagem pode ser exibida ao usuário."""


@dataclass
class IngestResult:
    document_id: str
    name: str
    page_count: int
    empty_pages: list[int]
    warnings: list[str] = field(default_factory=list)


def safe_display_name(filename: str) -> str:
    """Mantém só o nome do arquivo (sem diretórios) e remove caracteres de controle."""
    name = PureWindowsPath(PurePosixPath(filename).name).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:200] or "documento"


def ingest_document(
    conn: sqlite3.Connection,
    documents_dir: Path,
    notebook_id: str,
    filename: str,
    data: bytes,
    max_bytes: int,
) -> IngestResult:
    name = safe_display_name(filename)
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestError("Formato não suportado. Use PDF, DOCX, PPTX, TXT, MD ou CSV.")
    if not data:
        raise IngestError("Arquivo vazio.")
    if len(data) > max_bytes:
        raise IngestError(f"Arquivo maior que o limite de {max_bytes / 1024 / 1024:.0f} MB.")
    if not conn.execute("SELECT 1 FROM notebooks WHERE id = ?", (notebook_id,)).fetchone():
        raise IngestError("Notebook não encontrado.")

    digest = hashlib.sha256(data).hexdigest()
    dup = conn.execute(
        "SELECT name FROM documents WHERE notebook_id = ? AND sha256 = ?", (notebook_id, digest)
    ).fetchone()
    if dup:
        raise IngestError(f"Documento duplicado: o mesmo conteúdo já foi importado como \"{dup['name']}\".")

    try:
        extracted = extract(data, ext)
    except ExtractionError as exc:
        raise IngestError(str(exc)) from exc

    doc_id = str(uuid.uuid4())
    documents_dir.mkdir(parents=True, exist_ok=True)
    stored = documents_dir / f"{doc_id}{ext}"  # nunca usa o nome enviado pelo usuário no disco
    stored.write_bytes(data)
    try:
        with conn:
            conn.execute(
                """INSERT INTO documents (id, notebook_id, name, kind, sha256, size_bytes, stored_path,
                       paginated, page_count, empty_page_count, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, notebook_id, name, extracted.kind, digest, len(data), str(stored),
                 int(extracted.paginated), len(extracted.pages), len(extracted.empty_pages), now()),
            )
            conn.executemany(
                "INSERT INTO pages (document_id, page_number, text, char_count) VALUES (?, ?, ?, ?)",
                [(doc_id, p.number, p.text, len(p.text)) for p in extracted.pages],
            )
    except Exception:
        stored.unlink(missing_ok=True)
        raise
    return IngestResult(doc_id, name, len(extracted.pages), extracted.empty_pages, extracted.warnings)


def delete_document(conn: sqlite3.Connection, document_id: str) -> None:
    row = conn.execute("SELECT stored_path FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        return
    with conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    Path(row["stored_path"]).unlink(missing_ok=True)
