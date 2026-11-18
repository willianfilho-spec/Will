"""Conciliador Fortes — ponto de entrada (Streamlit).

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import config  # noqa: E402
from domain.operacoes import Contexto  # noqa: E402
from storage import usuarios  # noqa: E402
from storage.audit import registrar_acesso  # noqa: E402
from storage.database import conectar_central  # noqa: E402
from storage.usuarios import AcessoNegado  # noqa: E402
from ui import page_cadastros, page_cargas, page_exportacao, page_operador, page_revisao  # noqa: E402
from ui.comum import aviso_pendente, tratar_erros  # noqa: E402

st.set_page_config(page_title="Conciliador Fortes", page_icon="📒", layout="wide")


def primeira_execucao(central) -> None:
    st.title("Conciliador Fortes · primeira configuração")
    st.write(f"Dados locais em `{config.DATA_DIR}`. Crie o administrador e a primeira empresa.")
    with st.form("setup"):
        nome = st.text_input("Nome do administrador")
        email = st.text_input("E-mail (login)")
        senha = st.text_input("Senha (mín. 8)", type="password")
        st.divider()
        razao = st.text_input("Razão social da primeira empresa")
        cnpj = st.text_input("CNPJ")
        slug = st.text_input("Identificador da pasta (ex.: alfa-servicos)")
        if st.form_submit_button("Criar", type="primary"):
            with tratar_erros("Configuração criada. Entre com o e-mail e a senha."):
                central.execute("BEGIN IMMEDIATE")
                try:
                    uid = usuarios.criar_usuario(central, nome, email, senha, "admin")
                    usuarios.criar_empresa(central, slug.strip().lower(), razao, cnpj)
                    central.execute("COMMIT")
                except BaseException:
                    central.execute("ROLLBACK")
                    raise
                registrar_acesso(central, uid, None, "setup", "ok")


def login(central) -> None:
    st.title("Conciliador Fortes")
    aviso_pendente()
    with st.form("login"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            u = usuarios.autenticar(central, email, senha)
            registrar_acesso(central, u["id"] if u else None, None, "login", "ok" if u else "negado",
                             email=email.strip().lower())
            if u:
                st.session_state["usuario_id"] = u["id"]
                st.rerun()
            st.error("E-mail ou senha incorretos.")


def main() -> None:
    central = conectar_central()
    st.session_state["_central"] = central
    st.session_state.pop("_ctx", None)
    if central.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        primeira_execucao(central)
        return
    uid = st.session_state.get("usuario_id")
    usuario = central.execute("SELECT * FROM usuarios WHERE id = ? AND ativo = 1", (uid,)).fetchone() if uid else None
    if usuario is None:
        login(central)
        return
    st.session_state["_usuario"] = usuario

    with st.sidebar:
        st.markdown(f"**{usuario['nome']}** · {usuario['papel_global']}")
        empresas = usuarios.empresas_do_usuario(central, usuario["id"])
        if empresas:
            slugs = [e["slug"] for e in empresas]
            atual = st.session_state.get("empresa_slug")
            slug = st.selectbox("Empresa ativa", slugs, index=slugs.index(atual) if atual in slugs else 0,
                                format_func=lambda s: next(e["razao_social"] for e in empresas if e["slug"] == s))
            if slug != atual:
                st.session_state["empresa_slug"] = slug
            try:
                st.session_state["_ctx"] = Contexto.abrir(central, usuario, slug)
            except AcessoNegado as exc:
                st.error(str(exc))
        else:
            st.warning("Sem empresa liberada.")
        if st.button("Sair"):
            registrar_acesso(central, usuario["id"], None, "logout", "ok")
            st.session_state.clear()
            st.rerun()
        st.caption("Etapa A · uso interno · IA " + ("ligada (só sugere)" if config.ENABLE_AI else "desligada"))

    paginas = [
        st.Page(page_operador.render, title="Sessão", icon="👤", url_path="sessao", default=True),
        st.Page(page_cadastros.render, title="Cadastros", icon="📚", url_path="cadastros"),
        st.Page(page_cargas.render, title="Cargas", icon="📥", url_path="cargas"),
        st.Page(page_revisao.render, title="Revisão", icon="✅", url_path="revisao"),
        st.Page(page_exportacao.render, title="Conferência e exportação", icon="📤", url_path="exportacao"),
    ]
    st.navigation(paginas).run()


main()
