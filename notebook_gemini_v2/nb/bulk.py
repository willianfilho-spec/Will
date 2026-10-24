"""Importação em lote de arquivos de disco para um notebook (usada por importar.py)."""
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import repo
from .ingest import IngestError, ingest_document


@dataclass
class BulkReport:
    notebook_id: str
    created_notebook: bool
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # "arquivo: motivo"
    warnings: list[str] = field(default_factory=list)  # "arquivo: aviso"


def import_files(
    conn: sqlite3.Connection,
    documents_dir: Path,
    notebook_name: str,
    paths: list[Path],
    max_bytes: int,
) -> BulkReport:
    existing = repo.find_notebook_by_name(conn, notebook_name)
    nid = existing["id"] if existing else repo.create_notebook(conn, notebook_name)
    report = BulkReport(nid, created_notebook=existing is None)
    for path in paths:
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            report.skipped.append(f"{Path(path).name}: não foi possível ler o arquivo ({exc.strerror})")
            continue
        try:
            result = ingest_document(conn, documents_dir, nid, Path(path).name, data, max_bytes)
        except IngestError as exc:
            report.skipped.append(f"{Path(path).name}: {exc}")
            continue
        report.imported.append(f"{result.name} ({result.page_count} página(s)/unidade(s))")
        report.warnings.extend(f"{result.name}: {w}" for w in result.warnings)
    return report
