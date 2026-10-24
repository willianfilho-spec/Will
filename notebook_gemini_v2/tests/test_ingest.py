import pytest

from nb import repo
from nb.ingest import IngestError, delete_document, ingest_document, safe_display_name
from tests.conftest import make_docx, make_pdf

MAX = 5 * 1024 * 1024
PDF = make_pdf(["Artigo 1 - conteudo suficiente aqui", "Artigo 2 - outro conteudo suficiente"])


def test_importa_pdf_e_grava_paginas(conn, nid, docs_dir):
    r = ingest_document(conn, docs_dir, nid, "norma.pdf", PDF, MAX)
    assert r.page_count == 2 and r.empty_pages == []
    pages = repo.get_pages(conn, r.document_id)
    assert [p["page_number"] for p in pages] == [1, 2]
    doc = repo.list_documents(conn, nid)[0]
    assert doc["name"] == "norma.pdf" and doc["paginated"] == 1 and len(doc["sha256"]) == 64
    assert len(list(docs_dir.iterdir())) == 1


def test_duplicado_no_mesmo_notebook_e_recusado_mesmo_com_outro_nome(conn, nid, docs_dir):
    ingest_document(conn, docs_dir, nid, "a.pdf", PDF, MAX)
    with pytest.raises(IngestError, match="duplicado"):
        ingest_document(conn, docs_dir, nid, "copia-renomeada.pdf", PDF, MAX)
    assert len(repo.list_documents(conn, nid)) == 1
    assert len(list(docs_dir.iterdir())) == 1  # nada vazou para o disco


def test_mesmo_arquivo_em_outro_notebook_e_permitido(conn, nid, docs_dir):
    outro = repo.create_notebook(conn, "Outro")
    ingest_document(conn, docs_dir, nid, "a.pdf", PDF, MAX)
    ingest_document(conn, docs_dir, outro, "a.pdf", PDF, MAX)


def test_limite_de_tamanho(conn, nid, docs_dir):
    with pytest.raises(IngestError, match="limite"):
        ingest_document(conn, docs_dir, nid, "a.pdf", PDF, max_bytes=100)


def test_extensao_invalida_e_arquivo_vazio(conn, nid, docs_dir):
    with pytest.raises(IngestError, match="não suportado"):
        ingest_document(conn, docs_dir, nid, "virus.exe", b"x", MAX)
    with pytest.raises(IngestError, match="vazio"):
        ingest_document(conn, docs_dir, nid, "a.pdf", b"", MAX)


def test_pdf_digitalizado_nao_e_gravado(conn, nid, docs_dir):
    scan = make_pdf([None, None])
    with pytest.raises(IngestError, match="OCR"):
        ingest_document(conn, docs_dir, nid, "scan.pdf", scan, MAX)
    assert repo.list_documents(conn, nid) == []
    assert not docs_dir.exists() or list(docs_dir.iterdir()) == []


def test_pdf_parcialmente_digitalizado_importa_com_aviso(conn, nid, docs_dir):
    r = ingest_document(conn, docs_dir, nid, "misto.pdf", make_pdf(["Artigo 1 - texto suficiente aqui", None]), MAX)
    assert r.empty_pages == [2] and r.warnings
    assert repo.list_documents(conn, nid)[0]["empty_page_count"] == 1


def test_notebook_inexistente(conn, docs_dir):
    with pytest.raises(IngestError, match="Notebook"):
        ingest_document(conn, docs_dir, "nao-existe", "a.pdf", PDF, MAX)


@pytest.mark.parametrize(
    "entrada,esperado",
    [("../../etc/passwd.pdf", "passwd.pdf"), ("C:\\Users\\x\\norma.pdf", "norma.pdf"), ("a\x00b.pdf", "ab.pdf"), ("..", "documento"), ("", "documento")],
)
def test_nome_de_arquivo_seguro(entrada, esperado):
    assert safe_display_name(entrada) == esperado


def test_nome_enviado_nunca_vira_caminho_em_disco(conn, nid, docs_dir):
    ingest_document(conn, docs_dir, nid, "../../fora.pdf", PDF, MAX)
    arquivos = list(docs_dir.iterdir())
    assert len(arquivos) == 1 and arquivos[0].parent == docs_dir and "fora" not in arquivos[0].name


def test_excluir_remove_banco_paginas_e_arquivo(conn, nid, docs_dir):
    r = ingest_document(conn, docs_dir, nid, "a.pdf", PDF, MAX)
    delete_document(conn, r.document_id)
    assert repo.list_documents(conn, nid) == []
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
    assert list(docs_dir.iterdir()) == []


def test_falha_no_banco_nao_deixa_arquivo_orfao(conn, nid, docs_dir, monkeypatch):
    import nb.ingest as ing

    monkeypatch.setattr(ing.uuid, "uuid4", lambda: "id-fixo")
    conn.execute("CREATE TRIGGER falha BEFORE INSERT ON pages BEGIN SELECT RAISE(ABORT, 'falha simulada'); END")
    with pytest.raises(Exception, match="falha simulada"):
        ingest_document(conn, docs_dir, nid, "a.pdf", PDF, MAX)
    assert list(docs_dir.iterdir()) == []
    assert repo.list_documents(conn, nid) == []


def test_importa_docx(conn, nid, docs_dir):
    r = ingest_document(conn, docs_dir, nid, "x.docx", make_docx(["Paragrafo com texto suficiente."]), MAX)
    assert r.page_count == 1
    assert repo.get_pages(conn, r.document_id)[0]["page_number"] is None
