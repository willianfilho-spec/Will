"""Fluxo completo da tela para quem usa pela primeira vez: chave, notebook, envio e busca.
Usa a API simulada (sem rede): o que se testa aqui é a tela e o encadeamento, não o Gemini."""
import json

import pytest
from streamlit.testing.v1 import AppTest

from nb.connection import KeyCheck
from nb.embeddings import HashEmbedder
from tests.conftest import make_pdf

KEY = "AIza" + "x" * 35
APP = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    import nb.answer as answer
    import nb.connection as connection
    import nb.embeddings as embeddings

    monkeypatch.setattr(connection, "check_key", lambda key, client_factory=None: KeyCheck(
        len(key) > 20, "ok" if len(key) > 20 else "A chave parece incompleta.", ["gemini-2.5-flash"], ["gemini-embedding-001"]))
    monkeypatch.setattr(embeddings, "gemini_embedder", lambda key, model, dim: HashEmbedder(256) if key else None)

    def fake_ask(api_key, model, prompt):
        return json.dumps({"evidencia_suficiente": True, "afirmacoes": [
            {"tipo": "documentada", "texto": "Limite de créditos.", "fontes": ["F1"], "trecho": "limite mínimo de 12 e máximo de 32 créditos"}]})

    monkeypatch.setattr(answer, "ask", fake_ask)
    return tmp_path


def _run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_sem_chave_a_tela_so_pede_a_chave(fresh):
    at = _run(AppTest.from_file(APP, default_timeout=60))
    assert [h.value for h in at.subheader] == ["Passo 1 de 3 · Conectar ao Gemini"]
    assert len(at.tabs) == 0 and len(at.file_uploader) == 0


def test_chave_ruim_mostra_erro_e_nao_salva_chave_boa_salva_modelos_e_avanca(fresh):
    at = _run(AppTest.from_file(APP, default_timeout=60))
    at.text_input[0].set_value("curta"); at.button[0].click(); _run(at)
    assert at.error and not (fresh / "config.json").exists()
    at.text_input[0].set_value(KEY); at.button[0].click(); _run(at)
    saved = json.loads((fresh / "config.json").read_text())
    assert saved == {"api_key": KEY, "embedding_model": "gemini-embedding-001", "gemini_model": "gemini-2.5-flash"}
    assert [h.value for h in at.subheader][0] == "Passo 2 de 3 · Criar um notebook"


def test_fluxo_completo_envia_pdf_indexa_sozinho_e_responde_com_citacao_conferida(fresh, monkeypatch):
    (fresh / "config.json").write_text(json.dumps({"api_key": KEY, "embedding_model": "gemini-embedding-001"}), encoding="utf-8")
    at = _run(AppTest.from_file(APP, default_timeout=60))
    at.button[0].click(); _run(at)  # cria o notebook com o nome sugerido
    assert at.header[0].value == "Normas da Graduação"

    pdf = make_pdf(["Art. 118 A inscrição semestral observará o limite mínimo de 12 e máximo de 32 créditos por semestre."])
    at.file_uploader[0].upload("norma.pdf", pdf, "application/pdf"); _run(at)
    [b for b in at.button if b.label == "Importar documentos"][0].click(); _run(at)
    assert any("busca preparada" in s.value for s in at.success), [s.value for s in at.success]
    assert not at.warning  # nada pendente: a indexação foi automática
    assert len(at.file_uploader[0].value or []) == 0  # a caixa de envio foi esvaziada

    [t for t in at.text_area if t.label == "Sua pergunta"][0].set_value("Qual o limite de créditos por semestre?"); _run(at)
    [b for b in at.button if b.label == "Buscar"][0].click(); _run(at)
    texto = " ".join(m.value for m in at.markdown)
    assert "✅" in texto and "Limite de créditos." in texto and "Resposta verificada" in texto


def test_reenviar_o_mesmo_arquivo_avisa_duplicado_sem_travar(fresh):
    (fresh / "config.json").write_text(json.dumps({"api_key": KEY, "embedding_model": "gemini-embedding-001"}), encoding="utf-8")
    at = _run(AppTest.from_file(APP, default_timeout=60))
    at.button[0].click(); _run(at)
    pdf = make_pdf(["Art. 1 Texto suficiente para ser importado e indexado aqui."])
    for _ in range(2):
        at.file_uploader[0].upload("a.pdf", pdf, "application/pdf"); _run(at)
        [b for b in at.button if b.label == "Importar documentos"][0].click(); _run(at)
    assert any("duplicado" in e.value for e in at.error)
