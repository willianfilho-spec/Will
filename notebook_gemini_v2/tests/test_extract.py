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


def test_pdf_com_letras_sobrepostas_e_relido_por_segundo_extrator():
    from tests.conftest import make_shadow_pdf

    doc = extract(make_shadow_pdf("PONTO DE PARTIDA PARA COMECAR"), ".pdf")
    assert doc.pages[0].text == "PONTO DE PARTIDA PARA COMECAR"
    assert any("letras repetidas" in w for w in doc.warnings)


def test_texto_normal_com_poucas_palavras_curtas_nao_aciona_fallback():
    doc = extract(make_pdf(["Art. 1 O aluno deve entregar a documentacao e o historico no prazo"]), ".pdf")
    assert not any("letras repetidas" in w for w in doc.warnings)


def test_titulo_embaralhado_no_meio_de_texto_normal_tambem_aciona_fallback():
    from tests.conftest import make_shadow_pdf  # noqa: F401  (apenas garante o módulo)
    from nb.extract import _looks_garbled

    texto = "VISÃO GERAL\nN N NÃ Ã ÃO O O V V VA A AC C CI I IL LLE E E\nMade with Manus\nrodapé do documento aqui"
    assert _looks_garbled(texto)
    assert not _looks_garbled("Art. 5º O aluno deve solicitar a revisão no prazo de três dias úteis.\nA nota é a média final.")


def test_pptx_slide_vira_pagina_com_notas_e_aviso_de_slide_sem_texto():
    from tests.conftest import make_pptx

    data = make_pptx([["Aproveitamento de estudos", "Discente"], None, ["Documentos necessários para solicitação"]],
                     notes={3: "Lembrar do histórico"})
    doc = extract(data, ".pptx")
    assert doc.paginated and [p.number for p in doc.pages] == [1, 2, 3]
    assert "Aproveitamento de estudos\nDiscente" == doc.pages[0].text
    assert "Notas do apresentador: Lembrar do histórico" in doc.pages[2].text
    assert doc.empty_pages == [2] and "2" in doc.warnings[0]


def test_pptx_so_com_imagens_e_recusado_e_invalido_gera_erro():
    from tests.conftest import make_pptx

    with pytest.raises(ExtractionError, match="só imagens"):
        extract(make_pptx([None, None]), ".pptx")
    with pytest.raises(ExtractionError):
        extract(b"nao e pptx", ".pptx")
