from nb.answer import build_prompt, describe
from nb.rag import Hit


def _hit(i, nome, pagina, texto):
    return Hit(i, "d", nome, pagina, texto, 0.9)


def test_prompt_numera_trechos_com_arquivo_e_pagina_e_fixa_o_limite_de_marcadores():
    p = build_prompt("Qual o prazo?", [_hit(1, "norma.pdf", 3, "Art. 151 prazo de três dias"), _hit(2, "guia.docx", None, "Texto sem página")])
    assert "[F1] (norma.pdf, página 3)\nArt. 151 prazo de três dias" in p
    assert "[F2] (guia.docx, sem página)\nTexto sem página" in p
    assert "F1 a F2" in p and p.rstrip().endswith("Qual o prazo?")
    assert "APENAS os trechos" in p and "evidencia_suficiente" in p and "não um posicionamento oficial" in p


def test_prompt_com_chaves_no_texto_dos_trechos_nao_quebra_a_formatacao():
    p = build_prompt("Pergunta {x}?", [_hit(1, "a.pdf", 1, "Texto com {chaves} e {0} no meio")])
    assert "Texto com {chaves} e {0} no meio" in p and "Pergunta {x}?" in p


def test_describe():
    assert describe(_hit(1, "a.pdf", 7, "x")) == "a.pdf, página 7"
