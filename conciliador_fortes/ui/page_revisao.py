"""Fila de classificação, edição, duplicidades e segunda confirmação."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ai import suggester
from domain import operacoes as o
from domain.money import formatar_br
from ui.comum import (abas, aviso_pendente, exigir_contexto, opcoes_contas, pode_fazer, seletor_conta, tabela_movimentos,
                      tratar_erros)


def _rotulo(m) -> str:
    return f"#{m['id']} · {m['data']} · {formatar_br(m['valor_centavos'])} · {m['historico'][:60]}"


def render() -> None:
    c = exigir_contexto()
    aviso_pendente()
    st.header("Fila de classificação e segunda revisão")
    periodos = [r[0] for r in c.con.execute(
        "SELECT DISTINCT substr(data, 1, 7) FROM movimentos ORDER BY 1 DESC").fetchall()]
    if not periodos:
        st.info("Nenhum movimento carregado ainda.")
        return
    periodo = st.selectbox("Período", ["todos"] + periodos)
    filtro, params = ("", ()) if periodo == "todos" else (" AND substr(data, 1, 7) = ?", (periodo,))

    def q(cond):
        return c.con.execute(f"SELECT * FROM movimentos WHERE {cond}{filtro} ORDER BY data, id", params).fetchall()

    fila, segunda = q("status IN ('pendente', 'proposto')"), q(
        "status = 'classificado' AND exige_segunda_confirmacao = 1 AND segunda_confirmacao_por IS NULL")
    dups, espera = q("decisao_duplicidade = 'pendente'"), q("status = 'em_espera'")
    contagem = {"Fila": len(fila), "Segunda confirmação": len(segunda), "Duplicidades": len(dups),
                "Em espera": len(espera)}
    aba = abas(["Fila", "Segunda confirmação", "Duplicidades", "Em espera", "Todos"], "aba_rev",
               lambda n: f"{n} ({contagem[n]})" if n in contagem else n)
    contas = opcoes_contas()

    if aba == "Fila":
        propostos = [m for m in fila if m["status"] == "proposto"]
        if propostos and pode_fazer("classificar"):
            st.markdown("**Propostas geradas por regra.** Marque as que conferem e aceite em bloco.")
            todas = st.checkbox("Marcar todas", key=f"todas_{periodo}")
            df = pd.DataFrame([{"aceitar": todas, "id": m["id"], "data": m["data"],
                                "valor": formatar_br(m["valor_centavos"], False), "historico": m["historico"],
                                "debito": contas.get(m["conta_debito"], m["conta_debito"]),
                                "credito": contas.get(m["conta_credito"], m["conta_credito"]),
                                "risco": m["motivos_risco"] or ""} for m in propostos])
            ed = st.data_editor(df, hide_index=True, disabled=[c_ for c_ in df.columns if c_ != "aceitar"],
                                key=f"ed_prop_{periodo}_{todas}")
            if st.button("Aceitar propostas marcadas", type="primary"):
                with tratar_erros():
                    ids = ed.loc[ed["aceitar"], "id"].tolist()
                    por_id = {m["id"]: m for m in propostos}
                    for i in ids:
                        m = por_id[i]
                        contra = m["conta_debito"] if m["valor_centavos"] < 0 else m["conta_credito"]
                        o.classificar(c, i, contra, m["historico_contabil"], m["natureza"], "regra")
                    st.session_state["_aviso"] = f"{len(ids)} proposta(s) aceita(s)."
                    st.rerun()
        if fila:
            st.markdown("**Classificar um movimento**")
            mid = st.selectbox("Movimento", [m["id"] for m in fila],
                               format_func=lambda i: _rotulo(next(m for m in fila if m["id"] == i)))
            _editor(c, next(m for m in fila if m["id"] == mid))
        else:
            st.success("Fila vazia neste período.")

    if aba == "Segunda confirmação":
        st.caption("Itens de risco precisam da confirmação de outra pessoa, diferente de quem fez a revisão inicial.")
        if segunda:
            st.dataframe(tabela_movimentos(segunda), hide_index=True)
            mid = st.selectbox("Item", [m["id"] for m in segunda],
                               format_func=lambda i: _rotulo(next(m for m in segunda if m["id"] == i)), key="sel2")
            m = next(x for x in segunda if x["id"] == mid)
            st.write(f"Débito **{contas.get(m['conta_debito'], m['conta_debito'])}** · "
                     f"Crédito **{contas.get(m['conta_credito'], m['conta_credito'])}**")
            st.write(f"Motivo: {m['motivos_risco']} · Revisado por **{m['revisado_por']}** em {m['revisado_em']}")
            if not pode_fazer("segunda_confirmacao"):
                st.info("Seu papel não permite segunda confirmação.")
            elif m["revisado_por"] == c.nome:
                st.warning("Você fez a revisão inicial deste item. Outra pessoa precisa confirmar.")
            else:
                a, b = st.columns(2)
                if a.button("Confirmar", type="primary"):
                    with tratar_erros("Segunda confirmação registrada."):
                        o.segunda_confirmacao(c, mid)
                motivo = b.text_input("Motivo para devolver à fila")
                if b.button("Devolver"):
                    with tratar_erros("Item devolvido à fila."):
                        o.devolver(c, mid, motivo)
        else:
            st.success("Nada aguardando segunda confirmação.")

    if aba == "Duplicidades":
        st.caption("Nada é excluído automaticamente. Decida cada alerta; manter uma possível duplicidade exige segunda confirmação.")
        for m in dups:
            orig = c.con.execute("SELECT * FROM movimentos WHERE id = ?", (m["duplicidade_de"],)).fetchone()
            with st.container(border=True):
                st.write(f"**Novo:** {_rotulo(m)}")
                if orig:
                    st.write(f"**Já existente:** {_rotulo(orig)} ({orig['status']})")
                st.caption(m["motivo_duplicidade"])
                if pode_fazer("decidir_duplicidade"):
                    j = st.text_input("Justificativa", key=f"dj{m['id']}")
                    a, b = st.columns(2)
                    if a.button("Manter (não é duplicado)", key=f"dm{m['id']}"):
                        with tratar_erros("Mantido; o item vai exigir segunda confirmação."):
                            o.decidir_duplicidade(c, m["id"], "manter", j)
                    if b.button("Descartar (é duplicado)", key=f"dd{m['id']}"):
                        with tratar_erros("Descartado."):
                            o.decidir_duplicidade(c, m["id"], "descartar", j)
        if not dups:
            st.success("Nenhum alerta pendente.")

    if aba == "Em espera":
        st.caption("Itens em espera ficam fora do lote; os demais podem seguir em lote separado.")
        if espera:
            st.dataframe(tabela_movimentos(espera), hide_index=True)
            mid = st.selectbox("Retomar", [m["id"] for m in espera],
                               format_func=lambda i: _rotulo(next(m for m in espera if m["id"] == i)), key="selesp")
            if st.button("Retomar item"):
                with tratar_erros("Item retomado."):
                    o.retomar(c, mid)

    if aba == "Todos":
        st.dataframe(tabela_movimentos(q("1 = 1")), hide_index=True)


def _editor(c, m) -> None:
    pistas = o.pistas_planilha(c.con, m)
    if pistas:
        st.info("Pista na planilha de despesas: " + " | ".join(
            f"{p['data']} · {formatar_br(p['valor_centavos'])} · {p['descricao']}" for p in pistas[:3]))
    if m["observacao"]:
        st.caption(f"Observação: {m['observacao']}")
    if m["decisao_duplicidade"] == "pendente":
        st.warning("Este movimento tem alerta de duplicidade pendente (aba Duplicidades).")
    contra_atual = None
    if m["conta_debito"]:
        contra_atual = m["conta_debito"] if m["valor_centavos"] < 0 else m["conta_credito"]
    sug = suggester.sugerir(m["historico"], m["valor_centavos"], [dict(r) for r in o.contas_analiticas(c.con)])
    if sug:
        st.info(f"Sugestão da IA (não aprova nada): {sug.conta_contrapartida} — {sug.justificativa}")
    if not pode_fazer("classificar"):
        st.info("Seu papel não permite classificar.")
        return
    lado = "Saída: débito na contrapartida, crédito no banco" if m["valor_centavos"] < 0 else \
        "Entrada: débito no banco, crédito na contrapartida"
    st.caption(lado)
    with st.form(f"cls{m['id']}"):
        conta = seletor_conta("Contrapartida", f"ct{m['id']}", contra_atual, excluir=m["conta_banco"])
        hist = st.text_input("Histórico contábil", value=m["historico_contabil"] or m["historico"])
        nat = st.selectbox("Natureza", o.NATUREZAS, index=o.NATUREZAS.index(m["natureza"]),
                           help="transferência, tributo, sócio ou incerta. Sócio e incerta exigem segunda confirmação.")
        espera = st.text_input("Ou: o que falta para classificar (coloca em espera)")
        a, b = st.columns(2)
        ok = a.form_submit_button("Classificar", type="primary")
        esp = b.form_submit_button("Colocar em espera")
    if ok:
        with tratar_erros():
            if not conta:
                raise ValueError("escolha a contrapartida")
            origem = "regra" if m["status"] == "proposto" and conta == contra_atual else "manual"
            motivos = o.classificar(c, m["id"], conta, hist, nat, origem)
            st.session_state["_aviso"] = "Classificado." + (
                f" Exige segunda confirmação: {'; '.join(motivos)}." if motivos else "")
            st.rerun()
    if esp:
        with tratar_erros("Movimento em espera."):
            o.colocar_em_espera(c, m["id"], espera)
