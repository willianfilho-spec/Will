import pytest

from nb.extract import ExtractionError, extract
from tests.conftest import make_docx, make_pdf

P1 = "Artigo 1 - Primeira pagina com conteudo suficiente"
P2 = "Artigo 2 - Segunda pagina com outro conteudo"
P3 = "Artigo 3 - Terceira pagina com mais conteudo"


def test_pdf_preserva_numero_da_pagina():
    doc = extract(make_pdf([P1, P2, P3]), ".pdf")
    assert doc.paginated and [p.number for p in doc.pages] == [1, 2, 3]
    assert "Primeira" in doc.pages[0].text and "Segunda" in doc.pages[1].text and "Terceira" in doc.pages[2].text
    assert "Segunda" not in doc.pages[0].text


def test_pdf_com_paginas_sem_texto_gera_aviso_e_lista_paginas():
    doc = extract(make_pdf([P1, None, None, P2, None]), ".pdf")
    assert doc.empty_pages == [2, 3, 5]
    assert len(doc.pages) == 5  # a numeração não é deslocada
    assert "2-3, 5" in doc.warnings[0]


def test_pdf_totalmente_digitalizado_e_recusado_com_orientacao_de_ocr():
    with pytest.raises(ExtractionError, match="OCR"):
        extract(make_pdf([None, None]), ".pdf")


@pytest.mark.parametrize("lixo", [b"", b"isto nao e um pdf", b"%PDF-1.4\ncorrompido"])
def test_pdf_invalido_gera_erro_controlado(lixo):
    with pytest.raises(ExtractionError):
        extract(lixo, ".pdf")


def test_docx_inclui_tabelas_e_marca_titulos():
    data = make_docx(["Texto introdutorio do documento."], table=[["Prazo", "Dias uteis"], ["Recurso", "3"]], heading="Capitulo I")
    doc = extract(data, ".docx")
    texto = doc.pages[0].text
    assert not doc.paginated and doc.pages[0].number is None
    assert "# Capitulo I" in texto
    assert "Recurso | 3" in texto
    assert any("sem número de página" in w for w in doc.warnings)


def test_docx_invalido():
    with pytest.raises(ExtractionError):
        extract(b"nao e docx", ".docx")


def test_txt_utf8_e_fallback_cp1252():
    ok = extract("Ação e inscrição acadêmica válida".encode("utf-8"), ".txt")
    assert "Ação" in ok.pages[0].text and not ok.warnings
    legado = extract("Ação e inscrição acadêmica válida".encode("cp1252"), ".txt")
    assert "Ação" in legado.pages[0].text and legado.warnings


def test_arquivo_texto_vazio():
    with pytest.raises(ExtractionError):
        extract(b"   \n ", ".md")


def test_extensao_nao_suportada():
    with pytest.raises(ExtractionError):
        extract(b"abc", ".exe")


def test_ligaturas_viram_letras_comuns_mas_ordinais_sao_preservados():
    doc = extract("Art. 2º: diﬁculdades, ﬂuxos e eﬃciência, Nº 5ª".encode("utf-8"), ".txt")
    assert doc.pages[0].text == "Art. 2º: dificuldades, fluxos e efficiência, Nº 5ª"


def test_tab_vira_espaco_e_espacos_repetidos_sao_reduzidos():
    doc = extract("Instrução\tNormativa\tnº\t1731344/2025   publicada\n  segunda\tlinha".encode("utf-8"), ".txt")
    assert doc.pages[0].text == "Instrução Normativa nº 1731344/2025 publicada\nsegunda linha"


def test_marcador_de_lista_del_vira_bullet_e_controles_sao_removidos():
    doc = extract("Fontes:\x7fPró-Reitoria de Ensino\x00 e outras\x0c".encode("utf-8"), ".txt")
    assert doc.pages[0].text == "Fontes:•Pró-Reitoria de Ensino e outras"


def test_quebra_de_paragrafo_e_preservada():
    doc = extract("Primeiro parágrafo longo.\n\nSegundo parágrafo longo.".encode("utf-8"), ".txt")
    assert doc.pages[0].text == "Primeiro parágrafo longo.\n\nSegundo parágrafo longo."
