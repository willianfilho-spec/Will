import json

import streamlit as st
import streamlit.components.v1 as components

from nb import answer, citations, connection, pageview, rag, repo, settings_store
from nb.config import SUPPORTED_EXTENSIONS, load_settings
from nb.db import backup_legacy_database, connect
from nb.embeddings import EmbeddingError, gemini_embedder
from nb.ingest import IngestError, delete_document, ingest_document

settings = load_settings()

st.set_page_config(page_title="Notebook de Pesquisa com Gemini", page_icon="📚", layout="wide")
# O Streamlit declara a página como inglês e o Chrome oferece traduzir, o que embaralha os títulos.
# Isto avisa o navegador de que o texto já está em português (melhor esforço).
try:
    components.html(
        "<script>try{const d=window.parent.document;d.documentElement.lang='pt-BR';"
        "d.documentElement.setAttribute('translate','no');let m=d.querySelector('meta[name=google]');"
        "if(!m){m=d.createElement('meta');m.name='google';d.head.appendChild(m);}m.content='notranslate';}catch(e){}</script>",
        height=0,
    )
except Exception:  # versões novas do Streamlit podem remover esta função; o resto do app não depende dela
    pass
st.title("Notebook de Pesquisa com Gemini")
st.caption("Versão 2 em desenvolvimento · fases 0 a 3: importação, busca semântica e citações conferidas. Login e auditoria ainda não foram implementados.")


def connect_form(trocar: bool = False):
    """Cola da chave dentro da própria tela; o programa testa, descobre os modelos e salva."""
    with st.form("connect_form", clear_on_submit=False):
        key = st.text_input("Chave da API do Gemini", type="password", placeholder="Cole aqui (começa com AIza…)")
        if st.form_submit_button("Conectar" if not trocar else "Trocar chave", type="primary"):
            key = key.strip().strip("\"'").strip()
            with st.spinner("Testando a chave no Google..."):
                result = connection.check_key(key)
            if not result.ok:
                st.error(result.message)
                return
            embedding = connection.pick_embedding(result.embedding_models, settings.embedding_model)
            generation = connection.pick_generation(result.generation_models, settings.gemini_model)
            updates = {"api_key": key, "embedding_model": embedding}
            if generation:
                updates["gemini_model"] = generation
            settings_store.save(settings.data_dir, **updates)
            st.rerun()


def render_connection_gate() -> bool:
    """Devolve True quando já há chave. Sem chave, mostra o passo 1 e para por aqui."""
    if settings.gemini_api_key:
        with st.sidebar.expander("Conexão com o Gemini ✅"):
            st.caption(f"Chave: {settings_store.mask_key(settings.gemini_api_key)} (origem: {settings.key_source})")
            st.caption(f"Modelo de resposta: {settings.gemini_model}")
            st.caption(f"Modelo de busca: {settings.embedding_model}")
            connect_form(trocar=True)
        return True
    st.subheader("Passo 1 de 3 · Conectar ao Gemini")
    st.markdown(
        "1. Abra **https://aistudio.google.com/apikey** e entre com a sua conta Google.\n"
        "2. Clique em **Create API key** e depois no ícone de **copiar**.\n"
        "3. Cole a chave abaixo e clique em **Conectar**. Ela fica guardada só neste computador."
    )
    connect_form()
    return False


def main(conn):
    if "selected_notebook" not in st.session_state:
        st.session_state.selected_notebook = None
    if not render_connection_gate():
        return

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
        st.caption("A chave fica guardada só neste computador. Não a compartilhe.")

    nid = st.session_state.selected_notebook
    if not nid:
        st.subheader("Passo 2 de 3 · Criar um notebook")
        with st.form("first_notebook"):
            name = st.text_input("Dê um nome (por exemplo, o assunto dos documentos)", value="Normas da Graduação")
            if st.form_submit_button("Criar notebook", type="primary"):
                try:
                    st.session_state.selected_notebook = repo.create_notebook(conn, name)
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
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
    st.subheader("Passo 3 de 3 · Enviar documentos")
    for kind, text in st.session_state.pop("import_log", []):
        {"ok": st.success, "warn": st.warning, "err": st.error}[kind](text)
    limit_mb = settings.max_upload_bytes / 1024 / 1024
    uploader_key = f"uploader_{st.session_state.get('uploader_n', 0)}"
    uploaded = st.file_uploader(
        f"Escolha os arquivos (até {limit_mb:.0f} MB cada). Depois clique em Importar.",
        type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
        key=uploader_key,
    )
    if st.button("Importar documentos", disabled=not uploaded, type="primary"):
        log = []
        for f in uploaded:
            try:
                result = ingest_document(conn, settings.documents_dir, nid, f.name, f.getvalue(), settings.max_upload_bytes)
                log.append(("ok", f"{result.name}: {result.page_count} unidade(s) de texto importada(s)."))
                log += [("warn", f"{result.name}: {w}") for w in result.warnings]
            except IngestError as exc:
                log.append(("err", f"{f.name}: {exc}"))
            except Exception as exc:  # erro inesperado não deve derrubar a tela
                log.append(("err", f"{f.name}: erro inesperado ({type(exc).__name__})."))
        embedder = get_embedder()
        if embedder and rag.pending_documents(conn, nid, embedder):
            with st.spinner("Preparando a busca nos documentos (pode levar alguns minutos)..."):
                for name, outcome in rag.index_pending(conn, embedder, nid).items():
                    log.append(("ok", f"{name}: busca preparada ({outcome} trechos).") if isinstance(outcome, int) else ("err", f"{name}: {outcome}"))
        st.session_state["import_log"] = log
        st.session_state["uploader_n"] = st.session_state.get("uploader_n", 0) + 1  # esvazia a caixa de envio
        st.rerun()

    docs = repo.list_documents(conn, nid)
    if not docs:
        st.info("Este notebook ainda não tem documentos.")
        return
    embedder = get_embedder()
    pending = rag.pending_documents(conn, nid, embedder) if embedder else [d for d in docs if not d["indexed_model"]]
    if pending:
        st.warning(f"{len(pending)} documento(s) ainda sem índice de busca (isso costuma acontecer se a indexação automática falhou).")
        if st.button("Indexar documentos pendentes", disabled=embedder is None, type="primary"):
            with st.spinner("Gerando embeddings..."):
                results = rag.index_pending(conn, embedder, nid)
            for name, outcome in results.items():
                (st.success if isinstance(outcome, int) else st.error)(f"{name}: {outcome} trecho(s) indexado(s)" if isinstance(outcome, int) else f"{name}: {outcome}")
            if all(isinstance(v, int) for v in results.values()):
                st.rerun()
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
    st.info("A busca traz os trechos mais parecidos com a pergunta e só eles vão ao Gemini. O programa confere se cada citação literal da resposta existe no trecho indicado; isso não prova que o trecho sustenta a conclusão. Confira no documento original.")
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
                raw = answer.ask(settings.gemini_api_key, model.strip(), answer.build_prompt(question, hits))
        except Exception as exc:
            st.error(f"Erro na chamada da API Gemini: {exc}")
            raw = None
        if raw is not None:
            parsed = citations.parse_response(raw)
            checks = citations.verify(parsed, hits) if parsed.ok else []
            record = citations.to_json(parsed, checks, hits)
            repo.add_message(conn, nid, "user", question)
            repo.add_message(conn, nid, "assistant", raw, metadata=record)
            st.markdown("### Resposta verificada")
            render_verification(conn, json.loads(record), "novo")
            if not parsed.ok:
                st.markdown("**Resposta bruta do modelo (NÃO verificada):**")
                st.write(raw)
    st.markdown("### Trechos recuperados")
    st.caption("Pontuação = similaridade de cosseno com a pergunta. Pontuação alta não prova que o trecho responde.")
    for i, h in enumerate(hits, start=1):
        with st.expander(f"[{answer.label(i)}] {answer.describe(h)} · pontuação {h.score:.2f}", expanded=only_search and i <= 3):
            st.write(h.text)


ICONS = {"confirmada": "✅", "outro_trecho": "⚠️", "nao_confirmada": "❌", "sem_fonte": "⛔",
         "inferencia": "💡", "recomendacao": "📌", "formato_invalido": "❓"}
TIPOS = {"documentada": "Documentada", "inferencia": "Inferência", "recomendacao": "Recomendação"}


def render_verification(conn, data, prefix):
    parsed, summary = data["parsed"], data["summary"]
    if not parsed["ok"]:
        st.error(parsed["error"])
        return
    if parsed["evidencia_suficiente"] is False:
        st.warning("O modelo declarou que as fontes recuperadas NÃO são suficientes para responder com segurança.")
    if summary["nenhuma_confirmada"]:
        st.error("Nenhuma afirmação documentada teve a citação literal confirmada nos trechos. Não use esta resposta como está.")
    elif summary["documentadas"]:
        st.caption(f"{summary['confirmadas']} de {summary['documentadas']} afirmações documentadas com citação literal confirmada · {summary['problemas']} com problema · {summary['alertas']} alerta(s).")
    if not data["checks"]:
        st.info("O modelo não apresentou afirmações.")
    hits = {h["label"]: h for h in data["hits"]}
    for i, ck in enumerate(data["checks"]):
        claim = ck["claim"]
        st.markdown(f"{ICONS.get(ck['status'], '❓')} **{TIPOS.get(citations.fold(claim['tipo']), 'Tipo inválido')}** — {claim['texto']}")
        st.caption(citations.STATUS_LABEL[ck["status"]])
        for note in ck["notes"]:
            st.caption(f"⚠️ {note}")
        if claim["trecho"]:
            st.markdown("> " + claim["trecho"].replace("\n", " "))
        for src in ck["sources"]:
            where = f"página {src['page_number']}" if src["page_number"] is not None else "sem página"
            with st.expander(f"Conferir {src['label']} — {src['document_name']}, {where}"):
                st.write(hits[src["label"]]["text"])
                render_original(conn, src, f"{prefix}_{i}_{src['label']}")
    if parsed["divergencias"]:
        st.markdown("**Divergências apontadas pelo modelo:** " + "; ".join(parsed["divergencias"]))
    if parsed["lacunas"]:
        st.markdown(f"**Lacunas apontadas pelo modelo:** {parsed['lacunas']}")
    st.caption("Leitura automática dos documentos enviados; não é posicionamento oficial da instituição. A verificação confirma que a citação existe no trecho, não que o trecho sustente a conclusão.")


def render_original(conn, src, key):
    doc = pageview.original_file(conn, src["document_id"])
    if not doc:
        st.caption("Documento original não está mais no notebook.")
        return
    if doc["kind"] == "pdf" and src["page_number"] is not None and st.toggle("Mostrar a página original", key=f"pg_{key}"):
        png = pageview.render_pdf_page(doc["stored_path"], src["page_number"])
        if png:
            st.image(png, caption=f"{doc['name']}, página {src['page_number']} (numeração física do PDF)")
        else:
            st.caption("Não foi possível renderizar a página.")
    try:
        with open(doc["stored_path"], "rb") as fh:
            st.download_button("Baixar o documento original", fh.read(), file_name=doc["name"], key=f"dl_{key}")
    except OSError:
        st.caption("Arquivo original indisponível no disco.")


def render_history(conn, nid):
    history = repo.list_messages(conn, nid)
    if not history:
        st.info("Ainda não há perguntas registradas.")
    for n, m in enumerate(history):
        with st.expander(f"{'Você' if m['role'] == 'user' else 'Gemini'} · {m['created_at']}"):
            if m["metadata"]:
                render_verification(conn, json.loads(m["metadata"]), f"h{n}")
            else:
                st.markdown(m["content"])


_legacy_backup = backup_legacy_database(settings.db_path)
_conn = connect(settings.db_path)
if _legacy_backup:
    st.warning(f"Foi encontrado um banco de dados da versão antiga. Ele foi guardado como \"{_legacy_backup.name}\" (pasta data) e um banco novo foi criado. Reimporte os documentos.")
try:
    main(_conn)
finally:
    _conn.close()
