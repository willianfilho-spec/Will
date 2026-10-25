from nb import repo
from nb.bulk import import_files
from nb.config import load_settings
from tests.conftest import make_pdf

MAX = 5 * 1024 * 1024


def _arquivos(tmp_path):
    pdf = tmp_path / "norma.pdf"
    pdf.write_bytes(make_pdf(["Artigo 1 - conteudo suficiente aqui", "Artigo 2 - outro conteudo suficiente"]))
    md = tmp_path / "base.md"
    md.write_text("# Base\n\nTexto de resumo com conteúdo suficiente para importar.", encoding="utf-8")
    return pdf, md


def test_cria_notebook_e_importa_varios_arquivos(conn, docs_dir, tmp_path):
    pdf, md = _arquivos(tmp_path)
    r = import_files(conn, docs_dir, "Normas", [pdf, md], MAX)
    assert r.created_notebook and len(r.imported) == 2 and not r.skipped
    assert {d["name"] for d in repo.list_documents(conn, r.notebook_id)} == {"norma.pdf", "base.md"}


def test_reexecutar_nao_duplica_e_reaproveita_o_notebook(conn, docs_dir, tmp_path):
    pdf, md = _arquivos(tmp_path)
    first = import_files(conn, docs_dir, "Normas", [pdf, md], MAX)
    second = import_files(conn, docs_dir, "Normas", [pdf, md], MAX)
    assert not second.created_notebook and second.notebook_id == first.notebook_id
    assert not second.imported and len(second.skipped) == 2 and all("duplicado" in s for s in second.skipped)
    assert len(repo.list_notebooks(conn)) == 1 and len(repo.list_documents(conn, first.notebook_id)) == 2


def test_arquivo_inexistente_ou_invalido_vai_para_skipped_sem_interromper(conn, docs_dir, tmp_path):
    pdf, _ = _arquivos(tmp_path)
    ruim = tmp_path / "x.exe"
    ruim.write_bytes(b"abc")
    r = import_files(conn, docs_dir, "Normas", [tmp_path / "nao_existe.pdf", ruim, pdf], MAX)
    assert len(r.imported) == 1 and len(r.skipped) == 2
    assert any("não foi possível ler" in s for s in r.skipped) and any("não suportado" in s for s in r.skipped)


def test_limite_padrao_de_upload_e_50mb(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    assert load_settings().max_upload_bytes == 50 * 1024 * 1024
    monkeypatch.setenv("MAX_UPLOAD_MB", "lixo")
    assert load_settings().max_upload_bytes == 50 * 1024 * 1024
