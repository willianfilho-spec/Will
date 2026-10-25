"""Mostra a página original de um PDF como imagem, para conferir uma citação a olho,
independentemente da camada de texto extraída."""
import io
from pathlib import Path

import pypdfium2 as pdfium


def render_pdf_page(path: Path, page_number: int, scale: float = 1.4) -> bytes | None:
    """PNG da página (1 = primeira folha) ou None se não for possível renderizar."""
    try:
        pdf = pdfium.PdfDocument(str(path))
        if not 1 <= page_number <= len(pdf):
            return None
        buf = io.BytesIO()
        pdf[page_number - 1].render(scale=scale).to_pil().save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # arquivo ausente/corrompido: a tela cai no download do original
        return None


def original_file(conn, document_id: str):
    return conn.execute("SELECT name, kind, stored_path FROM documents WHERE id = ?", (document_id,)).fetchone()
