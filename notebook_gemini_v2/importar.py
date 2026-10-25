"""Importa arquivos para um notebook sem abrir o navegador.

Uso (no terminal, dentro da pasta do projeto):
    python importar.py "Nome do notebook" arquivo1.pdf arquivo2.md
    python importar.py --indexar "Nome do notebook" arquivo1.pdf     (também gera os embeddings)

Se o notebook já existir, os arquivos são acrescentados a ele. Arquivos repetidos são ignorados.
"""
import sys
from pathlib import Path

from nb.bulk import import_files
from nb.config import load_settings
from nb import rag
from nb.db import connect
from nb.embeddings import gemini_embedder


def main(argv: list[str]) -> int:
    indexar = "--indexar" in argv
    argv = [a for a in argv if a != "--indexar"]
    if len(argv) < 3:
        print(__doc__)
        return 2
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        report = import_files(conn, settings.documents_dir, argv[1], [Path(a) for a in argv[2:]], settings.max_upload_bytes)
        outcomes = {}
        if indexar:
            embedder = gemini_embedder(settings.gemini_api_key, settings.embedding_model, settings.embedding_dim)
            if embedder is None:
                print("Sem GEMINI_API_KEY no .env: documentos importados, mas NÃO indexados.")
            else:
                outcomes = rag.index_pending(conn, embedder, report.notebook_id)
    finally:
        conn.close()
    print(f"Notebook \"{argv[1]}\" {'criado' if report.created_notebook else 'já existia'}.")
    for item in report.imported:
        print(f"  importado: {item}")
    for item in report.skipped:
        print(f"  NÃO importado: {item}")
    for item in report.warnings:
        print(f"  aviso: {item}")
    for name, outcome in outcomes.items():
        print(f"  indexado: {name} ({outcome} trechos)" if isinstance(outcome, int) else f"  NÃO indexado: {name}: {outcome}")
    # Repetidos já importados não são erro; qualquer outro motivo de recusa é.
    return 1 if any("duplicado" not in item for item in report.skipped) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
