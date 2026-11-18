"""Conferência mensal de saldo, geração do lote para o Fortes e registro do retorno."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import json

from domain import homologacao
from domain import operacoes as o
from exporters import fortes_exporter
from domain.money import formatar_br
from ui.comum import (aviso_pendente, campo_valor, conta_banco_padrao, exigir_contexto, pode_fazer, seletor_conta,
                      tratar_erros)


def render() -> None:
    c = exigir_contexto()
    aviso_pendente()
    st.header("Conferência mensal e exportação para o Fortes")
    if not homologacao.aprovado(c.central, "H1"):
        st.warning("**Integração com o Fortes não homologada.** Nenhum lote gerado por este app foi conferido "
                   "depois de uma importação real. Use uma empresa de teste no Fortes até o item H1 ser aprovado.")
    periodos = [r[0] for r in c.con.execute(
        "SELECT DISTINCT substr(data, 1, 7) FROM movimentos ORDER BY 1 DESC").fetchall()]
    if not periodos:
        st.info("Nenhum movimento carregado ainda.")
        return
    a, b = st.columns(2)
    periodo = a.selectbox("Período", periodos)
    with b:
        conta = seletor_conta("Conta do banco", "exp_conta", conta_banco_padrao())
    if not conta:
        return

    st.subheader("1. Saldos do extrato")
    s = c.con.execute("SELECT * FROM saldos_extrato WHERE periodo = ? AND conta_banco = ?", (periodo, conta)).fetchone()
    if s:
        st.caption(f"Informado por {s['informado_por']} em {s['informado_em']}.")
    if pode_fazer("conciliar"):
        with st.form(f"saldos{periodo}{conta}"):
            x, y = st.columns(2)
            with x:
                ini = campo_valor("Saldo inicial do extrato", f"si{periodo}{conta}",
                                  s["saldo_inicial_centavos"] if s else None)
            with y:
                fim = campo_valor("Saldo final do extrato", f"sf{periodo}{conta}", s["saldo_final_centavos"] if s else None)
            if st.form_submit_button("Gravar saldos e conferir", type="primary"):
                with tratar_erros("Conferência atualizada."):
                    if ini is None or fim is None:
                        raise ValueError("informe os dois saldos (use 0,00 se for o caso)")
                    o.informar_saldos(c, periodo, conta, ini, fim)
                    o.conferir(c, periodo, conta)
        if s and st.button("Refazer conferência"):
            with tratar_erros("Conferência atualizada."):
                o.conferir(c, periodo, conta)

    st.subheader("2. Batimento")
    conc = o.conciliacao(c.con, periodo, conta)
    if conc:
        x, y, z, w = st.columns(4)
        x.metric("Saldo inicial (extrato)", formatar_br(conc["saldo_inicial_extrato"]))
        y.metric("Movimentação (extrato)", formatar_br(conc["movimentacao_extrato"]))
        z.metric("Saldo final (extrato)", formatar_br(conc["saldo_final_extrato"]))
        w.metric("Saldo final (contábil)", formatar_br(conc["saldo_final_contabil"]),
                 help="Razão importado + movimentos classificados ainda não encontrados no Razão")
        interna = conc["saldo_final_extrato"] - conc["saldo_inicial_extrato"] - conc["movimentacao_extrato"]
        if interna:
            st.error(f"O extrato não fecha com ele mesmo: diferença de {formatar_br(interna)}. "
                     "Falta movimento carregado ou o saldo informado está errado.")
        if not conc["razao_homologado"]:
            st.info(f"Conferência provisória: o Razão foi lido no formato '{conc['formato_razao'] or 'nenhum'}', "
                    "que ainda não foi homologado com um arquivo real do Fortes (item H3).")
        if conc["diferenca_centavos"]:
            st.error(f"Diferença extrato x contábil: **{formatar_br(conc['diferenca_centavos'])}** · "
                     f"status: {conc['status']}")
        else:
            st.success(f"Extrato e contabilidade batem · status: {conc['status']}")
        if conc["justificativa"]:
            st.write(f"Justificativa de {conc['justificado_por']}: {conc['justificativa']}")
            st.write(f"Segunda revisão: {conc['segunda_revisao_por'] or 'pendente'}")
        if conc["diferenca_centavos"]:
            if pode_fazer("conciliar"):
                with st.form("just"):
                    t = st.text_area("Explicação comprovada da diferença")
                    if st.form_submit_button("Registrar justificativa"):
                        with tratar_erros("Justificativa registrada; falta a segunda revisão."):
                            o.justificar_diferenca(c, periodo, conta, t)
            if conc["justificativa"] and not conc["segunda_revisao_por"] and pode_fazer("revisar_diferenca"):
                if conc["justificado_por"] == c.nome:
                    st.warning("Você registrou a justificativa; outra pessoa precisa revisar.")
                elif st.button("Revisar e aceitar a justificativa"):
                    with tratar_erros("Diferença revisada. A conciliação fica 'justificada', não 'concluída'."):
                        o.revisar_diferenca(c, periodo, conta)
    else:
        st.info("Informe os saldos e rode a conferência.")

    st.subheader("3. Lote para o Fortes")
    movs, problemas = o.pre_validar_lote(c, periodo, conta)
    st.write(f"{len(movs)} movimento(s) classificado(s) prontos · total "
             f"{formatar_br(sum(abs(m['valor_centavos']) for m in movs))}")
    so_vazio = problemas and all(p.startswith("nenhum movimento classificado") or p.startswith("há um lote")
                                 for p in problemas) and not movs
    if so_vazio:
        st.info("Nada novo para exportar neste período." + (" " + problemas[-1] if problemas[-1].startswith("há um lote") else ""))
    elif problemas:
        st.error("Validação pré-exportação: o lote está bloqueado.")
        st.markdown("\n".join(f"- {p}" for p in problemas[:60]))
    else:
        st.success("Todas as validações passaram.")
    if movs:
        lim = o.limite_historico(c.con)
        cortes = []
        for m in movs:
            mk = fortes_exporter.marca(c.prefixo, m["data"], m["id"])
            _, cortado = fortes_exporter.montar_historico(m["historico_contabil"] or m["historico"], mk, lim)
            if cortado:
                cortes.append({"id": m["id"], "histórico completo (fica guardado)": m["historico_contabil"] or m["historico"]})
        st.caption(f"Limite do histórico: {lim} caracteres (Cadastros > Parâmetros).")
        if cortes:
            st.warning(f"{len(cortes)} histórico(s) serão encurtados no arquivo. O texto completo fica no banco "
                       "e na lista de itens do lote.")
            st.dataframe(cortes, hide_index=True)
    if pode_fazer("exportar"):
        if st.button("Gerar lote", type="primary", disabled=bool(problemas)):
            with tratar_erros():
                r = o.gerar_lote(c, periodo, conta)
                st.session_state["_aviso"] = (f"Lote {r['lote_id']} gerado com {r['quantidade']} lançamentos "
                                              f"({formatar_br(r['total_centavos'])}). Baixe abaixo e importe no Fortes.")
                st.rerun()
    else:
        st.info("Seu papel não permite gerar lote.")
    st.caption('No Fortes, importe com "Desconsiderar Identificador" e "Utilizar Código Reduzido" marcados.')

    st.subheader("4. Lotes e retorno da importação")
    lotes = c.con.execute("SELECT * FROM lotes WHERE periodo = ? AND conta_banco = ? ORDER BY id DESC",
                          (periodo, conta)).fetchall()
    for lt in lotes:
        with st.container(border=True):
            st.write(f"**Lote {lt['id']}** · {lt['quantidade']} lançamentos · {formatar_br(lt['total_centavos'])} · "
                     f"gerado por {lt['gerado_por']} em {lt['gerado_em']} · **{lt['status']}**")
            st.caption(f"Limite do histórico usado: {lt['limite_historico'] or '-'} · históricos encurtados: "
                       f"{lt['truncados'] or 0} · SHA-256 {lt['sha256'][:16]}…")
            try:
                bruto = o.arquivo_lote(c, lt["id"])
                st.download_button("Baixar arquivo", bruto, file_name=(c.pasta / lt["caminho"]).name, mime="text/csv",
                                   key=f"dl{lt['id']}")
            except o.OperacaoInvalida as exc:
                st.error(str(exc))
            with st.expander("Itens do lote (linha exportada e histórico completo)"):
                st.dataframe([{"movimento": i["movimento_id"], "marca": i["marca"], "encurtado": bool(i["truncado"]),
                               "histórico completo": i["historico_completo"], "linha exportada": i["linha_exportada"]}
                              for i in o.itens_lote(c.con, lt["id"])], hide_index=True)
            if lt["status"] == "gerado" and pode_fazer("registrar_retorno"):
                obs = st.text_input("Observação / mensagem do Fortes", key=f"obs{lt['id']}")
                x, y = st.columns(2)
                if x.button("Importado sem erro", key=f"ac{lt['id']}"):
                    with tratar_erros("Retorno registrado: aceito."):
                        o.registrar_retorno(c, lt["id"], True, obs)
                if y.button("Rejeitado pelo Fortes", key=f"rj{lt['id']}"):
                    with tratar_erros("Retorno registrado: rejeitado. Os movimentos voltaram a 'classificado'."):
                        o.registrar_retorno(c, lt["id"], False, obs)
            elif lt["retorno_por"]:
                st.caption(f"Retorno de {lt['retorno_por']} em {lt['retorno_em']}: {lt['retorno_obs']}")
            if lt["status"] == "aceito":
                conf = json.loads(lt["conferencia_razao"]) if lt["conferencia_razao"] else None
                if conf:
                    (st.success if conf["aprovado"] else st.error)(
                        f"Conferência no Razão ({lt['conferido_por']}, {lt['conferido_em']}): "
                        f"{conf['encontrados']}/{conf['itens']} encontrados · ausentes {len(conf['ausentes'])} · "
                        f"divergentes {len(conf['divergentes'])} · duplicados {len(conf['duplicados'])}")
                    for p in (conf["ausentes"] + conf["divergentes"] + conf["duplicados"])[:30]:
                        st.markdown(f"- {p}")
                else:
                    st.info("Falta conferir este lote no Razão: exporte o Razão do Fortes depois da importação, "
                            "carregue em Cadastros > Razão e clique abaixo.")
                if pode_fazer("conciliar") and st.button("Conferir lote no Razão", key=f"cr{lt['id']}"):
                    with tratar_erros("Conferência no Razão registrada."):
                        o.conferir_lote_no_razao(c, lt["id"])
    if not lotes:
        st.caption("Nenhum lote neste período.")

    st.subheader("Relatório de pendências")
    if st.button("Gerar relatório de pendências (CSV)"):
        with tratar_erros():
            arq = o.relatorio_pendencias(c, periodo, conta)
            st.download_button("Baixar relatório", arq.read_bytes(), file_name=arq.name, mime="text/csv")
