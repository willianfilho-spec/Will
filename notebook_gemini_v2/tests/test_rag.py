import numpy as np
import pytest

from nb import rag, repo
from nb.embeddings import EmbeddingError, GeminiEmbedder, HashEmbedder, normalize
from nb.ingest import ingest_document
from tests.conftest import make_pdf

MAX = 5 * 1024 * 1024
PAGINAS = [
    "Art. 118 A inscrição semestral observará o limite mínimo de 12 e máximo de 32 créditos por semestre letivo.",
    "Art. 125 O trancamento de curso é a suspensão oficial das atividades acadêmicas, por no máximo quatro períodos.",
    "Art. 151 O pedido de reconsideração da nota será feito na coordenação em três dias úteis após a divulgação.",
]


@pytest.fixture
def emb():
    return HashEmbedder(dim=256)


@pytest.fixture
def doc(conn, nid, docs_dir):
    return ingest_document(conn, docs_dir, nid, "norma.pdf", make_pdf(PAGINAS), MAX).document_id


def test_indexa_e_recupera_o_trecho_certo_com_a_pagina(conn, nid, doc, emb):
    assert rag.index_document(conn, emb, doc) == 3
    hits = rag.search(conn, emb, nid, "prazo para pedir reconsideração da nota", top_k=2)
    assert hits[0].page_number == 3 and hits[0].document_name == "norma.pdf" and "Art. 151" in hits[0].text
    hits = rag.search(conn, emb, nid, "quantos períodos posso trancar o curso", top_k=1)
    assert hits[0].page_number == 2


def test_top_k_limita_e_ordena_por_score(conn, nid, doc, emb):
    rag.index_document(conn, emb, doc)
    hits = rag.search(conn, emb, nid, "créditos por semestre", top_k=2)
    assert len(hits) == 2 and hits[0].score >= hits[1].score and hits[0].page_number == 1
    assert len(rag.search(conn, emb, nid, "créditos por semestre", top_k=10)) == 3


def test_reindexar_nao_duplica_trechos(conn, nid, doc, emb):
    rag.index_document(conn, emb, doc)
    rag.index_document(conn, emb, doc)
    assert rag.chunk_count(conn, doc) == 3


def test_falha_de_embedding_nao_deixa_indice_parcial(conn, nid, doc):
    class Quebrado(HashEmbedder):
        def embed_documents(self, texts):
            raise EmbeddingError("cota esgotada")

    with pytest.raises(EmbeddingError):
        rag.index_document(conn, Quebrado(), doc)
    assert rag.chunk_count(conn, doc) == 0
    assert conn.execute("SELECT indexed_model FROM documents WHERE id=?", (doc,)).fetchone()[0] is None


def test_isolamento_entre_notebooks(conn, nid, doc, emb, docs_dir):
    outro = repo.create_notebook(conn, "Outro")
    doc2 = ingest_document(conn, docs_dir, outro, "outro.pdf", make_pdf(["Art. 9 Texto sobre biblioteca e empréstimo de livros."]), MAX).document_id
    rag.index_document(conn, emb, doc)
    rag.index_document(conn, emb, doc2)
    nomes = {h.document_name for h in rag.search(conn, emb, nid, "trancamento créditos biblioteca livros", top_k=10)}
    assert nomes == {"norma.pdf"}


def test_referencias_ficam_fora_da_busca_por_padrao(conn, nid, doc, emb):
    rag.index_document(conn, emb, doc)
    repo.set_doc_type(conn, doc, "referencia")
    assert rag.search(conn, emb, nid, "trancamento do curso") == []
    assert rag.search(conn, emb, nid, "trancamento do curso", doc_types=("conteudo", "referencia"))
    with pytest.raises(ValueError):
        repo.set_doc_type(conn, doc, "qualquer")


def test_filtro_por_documentos_selecionados(conn, nid, doc, emb, docs_dir):
    doc2 = ingest_document(conn, docs_dir, nid, "b.pdf", make_pdf(["Art. 1 Trancamento de matrícula em outro regulamento qualquer."]), MAX).document_id
    rag.index_document(conn, emb, doc)
    rag.index_document(conn, emb, doc2)
    assert {h.document_id for h in rag.search(conn, emb, nid, "trancamento", document_ids=[doc2])} == {doc2}
    assert rag.search(conn, emb, nid, "trancamento", document_ids=[]) == []


def test_modelo_diferente_exige_reindexar_e_nao_mistura_vetores(conn, nid, doc):
    a, b = HashEmbedder(256), HashEmbedder(128)
    rag.index_document(conn, a, doc)
    assert rag.pending_documents(conn, nid, a) == []
    assert [d["id"] for d in rag.pending_documents(conn, nid, b)] == [doc]
    assert rag.search(conn, b, nid, "trancamento") == []  # dimensão diferente: ignorado, sem erro
    assert rag.index_pending(conn, b, nid) == {"norma.pdf": 3}
    assert rag.search(conn, b, nid, "trancamento")


def test_consulta_vazia_e_notebook_sem_indice(conn, nid, emb):
    assert rag.search(conn, emb, nid, "   ") == []
    assert rag.search(conn, emb, nid, "qualquer coisa") == []


def test_normalize_zera_nada_e_deixa_norma_1():
    m = normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(np.linalg.norm(m[0]), 1.0) and np.allclose(m[1], 0.0)


class _Resp:
    def __init__(self, vectors):
        self.embeddings = [type("E", (), {"values": v})() for v in vectors]


class _Client:
    def __init__(self, dim=4, falhas=0):
        self.calls, self.dim, self.falhas = [], dim, falhas
        self.models = self

    def embed_content(self, model, contents, config):
        self.calls.append((model, list(contents), config))
        if self.falhas:
            self.falhas -= 1
            raise RuntimeError("503 indisponível")
        return _Resp([[float(i + 1)] * self.dim for i, _ in enumerate(contents)])


def test_gemini_embedder_monta_a_chamada_esperada_e_normaliza():
    client = _Client()
    e = GeminiEmbedder(client, "modelo-x", 4, sleep=lambda s: None)
    docs = e.embed_documents(["a", "b"])
    q = e.embed_query("pergunta")
    assert docs.shape == (2, 4) and np.allclose(np.linalg.norm(docs, axis=1), 1.0) and q.shape == (4,)
    model, contents, cfg = client.calls[0]
    assert model == "modelo-x" and contents == ["a", "b"]
    assert cfg.task_type == "RETRIEVAL_DOCUMENT" and cfg.output_dimensionality == 4
    assert client.calls[1][2].task_type == "RETRIEVAL_QUERY"


def test_gemini_embedder_divide_em_lotes_e_tenta_de_novo():
    client = _Client(falhas=2)
    e = GeminiEmbedder(client, "m", 4, sleep=lambda s: None)
    e.BATCH = 2
    assert e.embed_documents(["a", "b", "c"]).shape == (3, 4)
    assert [len(c[1]) for c in client.calls if True][-2:] == [2, 1]


def test_gemini_embedder_desiste_com_mensagem_clara_e_valida_dimensao():
    with pytest.raises(EmbeddingError, match="3 tentativas"):
        GeminiEmbedder(_Client(falhas=9), "m", 4, sleep=lambda s: None).embed_query("x")
    with pytest.raises(EmbeddingError, match="dimensões"):
        GeminiEmbedder(_Client(dim=3), "m", 4, sleep=lambda s: None).embed_query("x")


class _ErroApi(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class _ClienteComErro:
    def __init__(self, exc):
        self.exc, self.calls, self.models = exc, 0, self

    def embed_content(self, model, contents, config):
        self.calls += 1
        raise self.exc


def test_chave_invalida_vira_mensagem_clara_e_nao_repete_tentativas():
    erro = _ErroApi("400 INVALID_ARGUMENT. {'message': 'API key not valid. Please pass a valid API key.', 'reason': 'API_KEY_INVALID'}", 400)
    client = _ClienteComErro(erro)
    with pytest.raises(EmbeddingError, match="recusou a chave") as info:
        GeminiEmbedder(client, "m", 4, sleep=lambda s: None).embed_query("x")
    assert client.calls == 1 and "run.bat" in str(info.value)


def test_modelo_inexistente_e_permissao_negada_tem_mensagem_propria():
    with pytest.raises(EmbeddingError, match="GEMINI_EMBEDDING_MODEL"):
        GeminiEmbedder(_ClienteComErro(_ErroApi("404 NOT_FOUND models/xyz", 404)), "xyz", 4).embed_query("x")
    with pytest.raises(EmbeddingError, match="negou o acesso"):
        GeminiEmbedder(_ClienteComErro(_ErroApi("403 PERMISSION_DENIED", 403)), "m", 4).embed_query("x")


def test_erro_passageiro_continua_com_tentativas():
    client = _ClienteComErro(_ErroApi("503 UNAVAILABLE", 503))
    with pytest.raises(EmbeddingError, match="3 tentativas"):
        GeminiEmbedder(client, "m", 4, sleep=lambda s: None).embed_query("x")
    assert client.calls == 3


@pytest.mark.parametrize("bruto,esperado", [("cole_sua_chave_aqui", ""), ('"AIzaABC"', "AIzaABC"), ("  AIzaABC \n", "AIzaABC"), ("", "")])
def test_chave_do_env_e_limpa_e_o_texto_de_exemplo_conta_como_ausente(monkeypatch, bruto, esperado):
    from nb.config import load_settings

    monkeypatch.setenv("GEMINI_API_KEY", bruto)
    assert load_settings().gemini_api_key == esperado
