"""Importa arquivos para um notebook sem abrir o navegador.

Uso (no terminal, dentro da pasta do projeto):
    python importar.py "Nome do notebook" arquivo1.pdf arquivo2.md

Se o notebook já existir, os arquivos são acrescentados a ele. Arquivos repetidos são ignorados.
"""
import sys
from pathlib import Path

from nb.bulk import import_files
from nb.config import load_settings
from nb.db import connect


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        report = import_files(conn, settings.documents_dir, argv[1], [Path(a) for a in argv[2:]], settings.max_upload_bytes)
    finally:
        conn.close()
    print(f"Notebook \"{argv[1]}\" {'criado' if report.created_notebook else 'já existia'}.")
    for item in report.imported:
        print(f"  importado: {item}")
    for item in report.skipped:
        print(f"  NÃO importado: {item}")
    for item in report.warnings:
        print(f"  aviso: {item}")
    # Repetidos já importados não são erro; qualquer outro motivo de recusa é.
    return 1 if any("duplicado" not in item for item in report.skipped) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
