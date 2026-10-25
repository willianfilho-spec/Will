from nb.chunking import MAX_CHARS, chunk_pages, find_boilerplate


def test_nunca_atravessa_pagina_e_guarda_o_numero():
    pages = [(1, "Art. 1º Primeiro artigo com texto suficiente para virar trecho."),
             (2, "Art. 2º Segundo artigo com texto suficiente para virar trecho.")]
    chunks = chunk_pages(pages)
    assert [(c.page_number, c.text[:6]) for c in chunks] == [(1, "Art. 1"), (2, "Art. 2")]


def test_trechos_respeitam_o_tamanho_maximo_mesmo_sem_pontuacao():
    texto = " ".join(["palavra"] * 800)
    chunks = chunk_pages([(1, texto)])
    assert len(chunks) > 1 and all(len(c.text) <= MAX_CHARS for c in chunks)
    juntos = " ".join(c.text for c in chunks)
    assert juntos.count("palavra") >= 800  # nada se perde (pode haver sobreposição)


def test_artigos_curtos_sao_agrupados_ate_o_limite():
    pages = [(1, "\n".join(f"Art. {i} Texto do artigo número {i} com conteúdo suficiente." for i in range(1, 9)))]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1 and chunks[0].text.startswith("Art. 1") and "Art. 8" in chunks[0].text


def test_artigo_maior_que_o_limite_e_dividido_e_o_seguinte_fica_inteiro_em_um_trecho():
    longo = "Art. 1º " + "texto longo do artigo. " * 80
    seguinte = "Art. 2º Segundo artigo com conteúdo suficiente para ser indexado."
    chunks = chunk_pages([(1, f"{longo}\n{seguinte}")])
    assert len(chunks) >= 2 and all(len(c.text) <= MAX_CHARS for c in chunks)
    assert sum(seguinte in c.text for c in chunks) == 1


def test_remove_cabecalho_e_rodape_repetidos_mas_nao_o_conteudo():
    pages = [(i, f"UNIVERSIDADE FEDERAL DO MARANHÃO\n{i}\nArt. {i} Conteúdo específico da página {i} com texto suficiente.\nInstrução Normativa 99 / pg. {i}")
             for i in range(1, 6)]
    assert find_boilerplate([(n, t) for n, t in pages])
    for c in chunk_pages(pages):
        assert "UNIVERSIDADE" not in c.text and "pg." not in c.text and "Conteúdo específico" in c.text


def test_documento_curto_nao_remove_linhas_repetidas():
    pages = [(1, "Título importante repetido\nTexto de conteúdo suficiente aqui na primeira."),
             (2, "Título importante repetido\nTexto de conteúdo suficiente aqui na segunda.")]
    assert all("Título importante" in c.text for c in chunk_pages(pages))


def test_pagina_sem_numero_para_docx_e_trechos_minusculos_sao_descartados():
    chunks = chunk_pages([(None, "Texto de um documento sem páginas, com conteúdo suficiente.\n\nok")])
    assert len(chunks) == 1 and chunks[0].page_number is None
