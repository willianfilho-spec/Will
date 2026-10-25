from nb.answer import build_prompt, describe
from nb.rag import Hit


def _hit(i, nome, pagina, texto):
    return Hit(i, "d", nome, pagina, texto, 0.9)


def test_prompt_numera_trechos_com_arquivo_e_pagina():
    p = build_prompt("Qual o prazo?", [_hit(1, "norma.pdf", 3, "Art. 151 prazo de três dias"), _hit(2, "guia.docx", None, "Texto sem página")])
    assert "[F1] (norma.pdf, página 3)\nArt. 151 prazo de três dias" in p
    assert "[F2] (guia.docx, sem página)\nTexto sem página" in p
    assert p.rstrip().endswith("Qual o prazo?")
    assert "SOMENTE os trechos" in p and "evidência suficiente" in p


def test_describe():
    assert describe(_hit(1, "a.pdf", 7, "x")) == "a.pdf, página 7"
