import streamlit as st

from nb import gemini_v1, repo
from nb.config import SUPPORTED_EXTENSIONS, load_settings
from nb.db import connect
from nb.ingest import IngestError, delete_document, ingest_document

settings = load_settings()

st.set_page_config(page_title="Notebook de Pesquisa com Gemini", page_icon="📚", layout="wide")
st.title("Notebook de Pesquisa com Gemini")
st.caption("Versão 2 em desenvolvimento · fases 0 e 1: importação com páginas. Busca semântica, referências verificáveis e login ainda não foram implementados.")


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
    tab_docs, tab_chat, tab_history = st.tabs(["Documentos", "Perguntar ao Gemini", "Histórico"])

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
    for d in docs:
        label = f"{d['name']} · {d['page_count']} {'página(s)' if d['paginated'] else 'unidade'}"
        if d["empty_page_count"]:
            label += f" · ⚠️ {d['empty_page_count']} sem texto"
        with st.expander(label):
            st.caption(f"Adicionado em {d['added_at']} · {d['size_bytes'] / 1024:.0f} KB · SHA-256 {d['sha256'][:12]}…")
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


def render_chat(conn, nid):
    docs = repo.list_documents(conn, nid)
    if not docs:
        st.warning("Adicione documentos antes de fazer perguntas.")
        return
    st.info("Consulta simples da v1: envia o início de cada documento ao Gemini. A busca semântica (RAG) e as referências verificáveis entram na fase 2 e 3. Não trate as citações desta aba como verificadas.")
    by_id = {d["id"]: d["name"] for d in docs}
    chosen = st.multiselect("Fontes usadas nesta pergunta", list(by_id), default=list(by_id), format_func=by_id.get)
    per_doc = st.select_slider("Limite aproximado de caracteres por documento", options=[5000, 10000, 20000, 40000], value=10000)
    model = st.text_input("Modelo Gemini", value=settings.gemini_model)
    question = st.text_area("Sua pergunta")
    if st.button("Perguntar", type="primary", disabled=not question.strip() or not chosen):
        if not settings.gemini_api_key:
            st.error("Configure GEMINI_API_KEY no arquivo .env.")
            return
        payload = [(by_id[i], [(p["page_number"], p["text"]) for p in repo.get_pages(conn, i)]) for i in chosen]
        try:
            with st.spinner("Consultando o Gemini..."):
                answer = gemini_v1.ask(settings.gemini_api_key, model.strip(), gemini_v1.build_sources(payload, per_doc), question)
        except Exception as exc:
            st.error(f"Erro na chamada da API Gemini: {exc}")
            return
        repo.add_message(conn, nid, "user", question)
        repo.add_message(conn, nid, "assistant", answer)
        st.markdown("### Resposta")
        st.markdown(answer)


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
