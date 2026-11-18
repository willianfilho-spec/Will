"""Etapa A: empresa ativa, operador da sessão e administração básica."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from domain.money import formatar_br
from domain import homologacao as hom
from domain import operacoes as o
from storage import audit, backup, usuarios
from ui.comum import abas, aviso_pendente, campo_valor, ctx, pode_fazer, tratar_erros


def render() -> None:
    aviso_pendente()
    c = ctx()
    st.header("Sessão")
    if c is None:
        st.info("Nenhuma empresa disponível para este usuário. Peça a um administrador para conceder acesso.")
    else:
        papel = usuarios.papel_na_empresa(c.central, c.usuario["id"], c.empresa["id"])
        col1, col2, col3 = st.columns(3)
        col1.metric("Operador", c.usuario["nome"])
        col2.metric("Empresa ativa", c.empresa["razao_social"])
        col3.metric("Papel nesta empresa", papel or "-")
        st.caption(f"Limite para segunda revisão: {formatar_br(c.empresa['limite_revisao_centavos'])} · "
                   f"Toda ação desta sessão é gravada com o nome do operador.")
        resumo = c.con.execute("SELECT status, COUNT(*) n, SUM(ABS(valor_centavos)) t FROM movimentos GROUP BY status").fetchall()
        if resumo:
            st.subheader("Movimentos da empresa")
            st.dataframe(pd.DataFrame([{"status": r["status"], "quantidade": r["n"],
                                        "total": formatar_br(r["t"] or 0, simbolo=False)} for r in resumo]),
                         hide_index=True)

    central = st.session_state["_central"]
    usuario = st.session_state["_usuario"]
    if usuario["papel_global"] == "admin":
        _admin(central)
    if c is not None and pode_fazer("backup"):
        _backup()
    if c is not None:
        st.divider()
        st.subheader("Integridade")
        st.caption("Confere os arquivos originais e os lotes contra o SHA-256 gravado e o banco contra o integrity_check.")
        if st.button("Verificar integridade da empresa"):
            with tratar_erros():
                prob = o.verificar_integridade(c)
                st.success("Nenhum problema encontrado.") if not prob else st.error("\n".join(f"- {p}" for p in prob))
    _homologacao(central, usuario)
    if c is not None:
        with st.expander("Auditoria da empresa (últimas 200 ações)"):
            st.dataframe(pd.DataFrame([dict(r) for r in audit.listar(c.con)]), hide_index=True)


def _admin(central) -> None:
    st.divider()
    st.subheader("Administração")
    aba = abas(["Usuários", "Empresas", "Permissões"], "aba_adm")
    if aba == "Usuários":
        with st.form("novo_usuario", clear_on_submit=True):
            nome = st.text_input("Nome")
            email = st.text_input("E-mail (login)")
            senha = st.text_input("Senha inicial (mín. 8)", type="password")
            papel = st.selectbox("Papel global", config.PAPEIS_GLOBAIS, index=1)
            if st.form_submit_button("Criar usuário"):
                with tratar_erros(f"Usuário {nome} criado."):
                    usuarios.criar_usuario(central, nome, email, senha, papel)
        st.dataframe(pd.DataFrame([dict(r) for r in central.execute(
            "SELECT id, nome, email, papel_global, ativo, criado_em FROM usuarios ORDER BY nome")]), hide_index=True)
    if aba == "Empresas":
        with st.form("nova_empresa", clear_on_submit=True):
            razao = st.text_input("Razão social")
            cnpj = st.text_input("CNPJ")
            slug = st.text_input("Identificador da pasta (ex.: alfa-servicos)")
            limite = campo_valor("Limite para segunda revisão (R$)", "lim_emp", config.LIMITE_REVISAO_PADRAO_CENTAVOS)
            if st.form_submit_button("Criar empresa"):
                with tratar_erros(f"Empresa {razao} criada com banco e pasta próprios."):
                    usuarios.criar_empresa(central, slug.strip().lower(), razao, cnpj,
                                           limite or config.LIMITE_REVISAO_PADRAO_CENTAVOS)
        st.dataframe(pd.DataFrame([dict(r) for r in central.execute("SELECT * FROM empresas ORDER BY razao_social")]),
                     hide_index=True)
    if aba == "Permissões":
        us = central.execute("SELECT id, nome FROM usuarios WHERE ativo = 1 ORDER BY nome").fetchall()
        es = central.execute("SELECT id, razao_social FROM empresas WHERE ativa = 1 ORDER BY razao_social").fetchall()
        if us and es:
            with st.form("permissao"):
                u = st.selectbox("Usuário", [r["id"] for r in us], format_func=lambda i: next(r["nome"] for r in us if r["id"] == i))
                e = st.selectbox("Empresa", [r["id"] for r in es],
                                 format_func=lambda i: next(r["razao_social"] for r in es if r["id"] == i))
                p = st.selectbox("Papel na empresa", config.PAPEIS_EMPRESA, index=1)
                st.caption("operador: carrega e classifica · revisor: também dá segunda confirmação e exporta · "
                           "aprovador: tudo, inclusive backup · cliente: só envia arquivos (Etapa B)")
                if st.form_submit_button("Conceder"):
                    with tratar_erros("Permissão gravada."):
                        usuarios.conceder(central, u, e, p)
        st.dataframe(pd.DataFrame([dict(r) for r in central.execute(
            "SELECT u.nome, e.razao_social, p.papel_empresa FROM permissoes_empresa p "
            "JOIN usuarios u ON u.id = p.usuario_id JOIN empresas e ON e.id = p.empresa_id ORDER BY u.nome")]),
            hide_index=True)


def _backup() -> None:
    st.divider()
    st.subheader("Backup")
    st.caption(f"Destino: {config.BACKUP_DIR}. Copie a pasta para outro disco; backup no mesmo disco não protege de falha física.")
    if st.button("Fazer backup agora"):
        with tratar_erros():
            pasta = backup.criar_backup(config.DATA_DIR, config.BACKUP_DIR)
            prob = backup.verificar_backup(pasta)
            if prob:
                st.error("Backup criado com problema: " + "; ".join(prob))
            else:
                st.success(f"Backup íntegro em {pasta}")
    if config.BACKUP_DIR.exists():
        pastas = sorted((p for p in config.BACKUP_DIR.iterdir() if p.is_dir()), reverse=True)[:10]
        if pastas:
            escolhido = st.selectbox("Verificar um backup existente", pastas, format_func=lambda p: p.name)
            if st.button("Verificar integridade"):
                prob = backup.verificar_backup(escolhido)
                st.success("Íntegro.") if not prob else st.error("; ".join(prob))
            st.caption("Para restaurar: `python scripts/restaurar_backup.py <pasta-do-backup> <nova-pasta-de-dados>` "
                       "e aponte CONCILIADOR_DATA_DIR para a nova pasta.")


def _homologacao(central, usuario) -> None:
    st.divider()
    st.subheader("Homologação (P-004)")
    st.caption("Itens que dependem da instalação real do Fortes. Só viram 'aprovado' com evidência anexada; "
               "testes automatizados não aprovam nenhum deles. Procedimento: docs/conciliador-fortes/homologacao/.")
    est = hom.estado(central)
    linhas = []
    for cod, item in hom.ITENS.items():
        r = est[cod]
        linhas.append({"item": cod, "título": item.titulo, "status": r["status"] if r else "não testado",
                       "referência": r["referencia"] if r else "", "por": r["registrado_por"] if r else "",
                       "em": r["registrado_em"] if r else "",
                       "evidência íntegra": {True: "sim", False: "NÃO", None: "-"}[hom.evidencia_integra(r)] if r else "-"})
    st.dataframe(pd.DataFrame(linhas), hide_index=True)
    (st.success if hom.integracao_liberada(central) else st.warning)(
        "Integração liberada: todos os itens aprovados." if hom.integracao_liberada(central)
        else "Integração com o Fortes NÃO liberada: há itens não aprovados.")
    if usuario["papel_global"] != "admin":
        return
    with st.expander("Registrar resultado de teste"):
        with st.form("hom", clear_on_submit=True):
            cod = st.selectbox("Item", list(hom.ITENS), format_func=lambda k: f"{k} · {hom.ITENS[k].titulo}")
            st.caption("Critério e referência de cada item: " + " | ".join(
                f"{k}: {i.referencia}" for k, i in hom.ITENS.items()))
            status = st.selectbox("Status", ["em_teste", "aprovado", "reprovado"])
            teste = st.text_area("Teste realizado (o que foi feito, em qual empresa/arquivo)")
            resultado = st.text_area("Resultado observado")
            falha = st.text_input("Falha identificada (obrigatória se reprovado)")
            acao = st.text_input("Ação corretiva (obrigatória se reprovado)")
            ref = st.text_input("Referência")
            ev = st.file_uploader("Evidência (print, PDF do Razão, JSON do teste de restauração...)")
            if st.form_submit_button("Registrar"):
                with tratar_erros(f"Resultado do {cod} registrado."):
                    hom.registrar(central, usuario, cod, status, teste, resultado, falha, acao,
                                  ev.name if ev else None, ev.getvalue() if ev else None, ref)
    with st.expander("Histórico completo dos registros"):
        st.dataframe(pd.DataFrame([dict(r) for r in hom.historico(central)]), hide_index=True)
