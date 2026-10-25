from nb.pageview import render_pdf_page
from tests.conftest import make_pdf


def test_renderiza_pagina_existente_como_png_e_recusa_pagina_inexistente(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf(["Artigo 1 texto suficiente", "Artigo 2 texto suficiente"]))
    png = render_pdf_page(pdf, 2)
    assert png and png.startswith(b"\x89PNG")
    assert render_pdf_page(pdf, 3) is None and render_pdf_page(pdf, 0) is None


def test_arquivo_ausente_ou_corrompido_devolve_none(tmp_path):
    assert render_pdf_page(tmp_path / "nao_existe.pdf", 1) is None
    ruim = tmp_path / "x.pdf"
    ruim.write_bytes(b"lixo")
    assert render_pdf_page(ruim, 1) is None
