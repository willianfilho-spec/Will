import streamlit as st

from nb import answer, rag, repo
from nb.config import SUPPORTED_EXTENSIONS, load_settings
from nb.db import connect
from nb.embeddings import EmbeddingError, gemini_embedder
from nb.ingest import IngestError, delete_document, ingest_document

settings = load_settings()

st.set_page_config(page_title="Notebook de Pesquisa com Gemini", page_icon="📚", layout="wide")
st.title("Notebook de Pesquisa com Gemini")
st.caption("Versão 2 em desenvolvimento · fases 0 a 2: importação com páginas e busca semântica. Citações verificadas, login e auditoria ainda não foram implementados.")


def main(conn):
    if "selected_notebook" not in st.session_state:
        st.session_state.selected_notebook = None

    with st.sidebar:
        st.subheader("Notebooks")
        notebooks = repo.list_notebooks(conn)
        if notebooks:
            ids = [n["id"] for n in notebooks]
            current = st.session_state.selected_notebook
            index = ids.index(current) if current in ids else 0
            chosen = st.selectbox("Abrir notebook", ids, index=index, format_func=lambda i: next(n["name"] for n in notebooks if n["id"] == i))
            st.session_state.selected_notebook = chosen
        else:
            st.info("Crie seu primeiro notebook.")
        with st.form("new_notebook", clear_on_submit=True):
            new_name = st.text_input("Nome do novo notebook", placeholder="Ex.: Normas e procedimentos DIOAC")
            if st.form_submit_button("Criar notebook", use_container_width=True):
                try:
                    st.session_state.selected_notebook = repo.create_notebook(conn, new_name)
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
        st.divider()
        st.caption("A chave da API é lida do arquivo .env. Não a compartilhe.")

    nid = st.session_state.selected_notebook
    if not nid:
        st.info("Crie um notebook na barra lateral para começar.")
        return

    notebook = next(n for n in repo.list_notebooks(conn) if n["id"] == nid)
    st.header(notebook["name"])
    tab_docs, tab_chat, tab_history = st.tabs(["Documentos", "Perguntar", "Histórico"])

    with tab_docs:
        render_documents(conn, nid)
    with tab_chat:
        render_chat(conn, nid)
    with tab_history:
        render_history(conn, nid)


def render_documents(conn, nid):
    st.subheader("Adicionar fontes")
    limit_mb = settings.max_upload_bytes / 1024 / 1024
    uploaded = st.file_uploader(
        f"Envie documentos (até {limit_mb:.0f} MB cada)",
        type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
    )
    if st.button("Importar documentos", disabled=not uploaded):
        for f in uploaded:
            try:
                result = ingest_document(conn, settings.documents_dir, nid, f.name, f.getvalue(), settings.max_upload_bytes)
                st.success(f"{result.name}: {result.page_count} unidade(s) de texto importada(s).")
                for w in result.warnings:
                    st.warning(f"{result.name}: {w}")
            except IngestError as exc:
                st.error(f"{f.name}: {exc}")
            except Exception as exc:  # erro inesperado não deve derrubar a tela
                st.error(f"{f.name}: erro inesperado ({type(exc).__name__}).")

    docs = repo.list_documents(conn, nid)
    if not docs:
        st.info("Este notebook ainda não tem documentos.")
        return
    embedder = get_embedder()
    pending = rag.pending_documents(conn, nid, embedder) if embedder else [d for d in docs if not d["indexed_model"]]
    if pending:
        st.warning(f"{len(pending)} documento(s) ainda sem índice de busca.")
        if st.button("Indexar documentos pendentes", disabled=embedder is None, type="primary"):
            with st.spinner("Gerando embeddings..."):
                results = rag.index_pending(conn, embedder, nid)
            for name, outcome in results.items():
                (st.success if isinstance(outcome, int) else st.error)(f"{name}: {outcome} trecho(s) indexado(s)" if isinstance(outcome, int) else f"{name}: {outcome}")
            st.rerun() if all(isinstance(v, int) for v in results.values()) else None
        if embedder is None:
            st.caption("Configure GEMINI_API_KEY no arquivo .env para indexar.")
    for d in docs:
        label = f"{d['name']} · {d['page_count']} {'página(s)' if d['paginated'] else 'unidade'}"
        if d["empty_page_count"]:
            label += f" · ⚠️ {d['empty_page_count']} sem texto"
        current_model = embedder.model if embedder else d["indexed_model"]
        label += " · indexado" if d["indexed_model"] and d["indexed_model"] == current_model else " · sem índice"
        if d["doc_type"] != "conteudo":
            label += f" · tipo: {d['doc_type']}"
        with st.expander(label):
            st.caption(f"Adicionado em {d['added_at']} · {d['size_bytes'] / 1024:.0f} KB · SHA-256 {d['sha256'][:12]}…")
            current = rag.DOC_TYPES.index(d["doc_type"])
            new_type = st.selectbox(
                "Tipo do documento (só 'conteudo' é usado nas respostas)", rag.DOC_TYPES, index=current,
                key=f"type_{d['id']}", help="conteudo = norma, guia ou texto que sustenta respostas; referencia = lista de links ou bibliografia; material = peças gráficas, formulários etc.",
            )
            if new_type != d["doc_type"]:
                repo.set_doc_type(conn, d["id"], new_type)
                st.rerun()
            pages = repo.get_pages(conn, d["id"])
            if d["paginated"]:
                numbers = [p["page_number"] for p in pages]
                n = st.selectbox("Pré-visualizar página (numeração física do PDF)", numbers, key=f"pg_{d['id']}")
                page = next(p for p in pages if p["page_number"] == n)
            else:
                page = pages[0]
            if page["char_count"] == 0:
                st.warning("Esta página não tem texto extraível.")
            st.text_area("Texto extraído", page["text"][:5000], height=200, disabled=True, key=f"tx_{d['id']}_{page['page_number']}")
            if st.button("Excluir documento", key=f"del_{d['id']}"):
                delete_document(conn, d["id"])
                st.rerun()


def get_embedder():
    return gemini_embedder(settings.gemini_api_key, settings.embedding_model, settings.embedding_dim)


def render_chat(conn, nid):
    docs = [d for d in repo.list_documents(conn, nid) if d["doc_type"] == "conteudo"]
    if not docs:
        st.warning("Este notebook não tem documentos do tipo 'conteudo'. Importe um documento ou altere o tipo na aba Documentos.")
        return
    embedder = get_embedder()
    if embedder is None:
        st.error("Configure GEMINI_API_KEY no arquivo .env para buscar e perguntar.")
        return
    pending = rag.pending_documents(conn, nid, embedder)
    if pending:
        st.warning(f"{len(pending)} documento(s) sem índice com o modelo atual; eles não entram na busca. Indexe na aba Documentos.")
    st.info("A busca traz os trechos mais parecidos com a pergunta e só eles vão ao Gemini. Os marcadores [F1], [F2]... da resposta ainda NÃO são validados automaticamente (fase 3): confira cada um no trecho e no documento original.")
    by_id = {d["id"]: d["name"] for d in docs}
    chosen = st.multiselect("Fontes usadas nesta pergunta", list(by_id), default=list(by_id), format_func=by_id.get)
    top_k = st.slider("Quantidade de trechos recuperados", 1, 30, settings.top_k)
    model = st.text_input("Modelo Gemini", value=settings.gemini_model)
    only_search = st.checkbox("Só buscar trechos (não pedir resposta ao Gemini)")
    question = st.text_area("Sua pergunta")
    if not st.button("Buscar", type="primary", disabled=not question.strip() or not chosen):
        return
    try:
        with st.spinner("Buscando trechos..."):
            hits = rag.search(conn, embedder, nid, question, top_k=top_k, document_ids=chosen)
    except EmbeddingError as exc:
        st.error(str(exc))
        return
    if not hits:
        st.warning("Nenhum trecho encontrado. Verifique se os documentos estão indexados.")
        return
    if not only_search:
        try:
            with st.spinner("Consultando o Gemini..."):
                text = answer.ask(settings.gemini_api_key, model.strip(), answer.build_prompt(question, hits))
        except Exception as exc:
            st.error(f"Erro na chamada da API Gemini: {exc}")
            text = None
        if text:
            repo.add_message(conn, nid, "user", question)
            repo.add_message(conn, nid, "assistant", text)
            st.markdown("### Resposta")
            st.markdown(text)
    st.markdown("### Trechos recuperados")
    st.caption("Pontuação = similaridade de cosseno com a pergunta. Pontuação alta não prova que o trecho responde.")
    for i, h in enumerate(hits, start=1):
        with st.expander(f"[{answer.label(i)}] {answer.describe(h)} · pontuação {h.score:.2f}", expanded=only_search and i <= 3):
            st.write(h.text)


def render_history(conn, nid):
    history = repo.list_messages(conn, nid)
    if not history:
        st.info("Ainda não há perguntas registradas.")
    for m in history:
        with st.expander(f"{'Você' if m['role'] == 'user' else 'Gemini'} · {m['created_at']}"):
            st.markdown(m["content"])


_conn = connect(settings.db_path)
try:
    main(_conn)
finally:
    _conn.close()
