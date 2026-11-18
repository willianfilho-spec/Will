"""Plano de contas, Razão, regras recorrentes, sócios e parâmetros da empresa."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from domain import operacoes as o
from domain.money import formatar_br
from parsers.tabular_parser import ler_tabela
from ui.comum import (abas, aviso_pendente, campo_valor, conta_banco_padrao, exigir_contexto, opcoes_contas, pode_fazer,
                      seletor_conta, tratar_erros)


def render() -> None:
    c = exigir_contexto()
    aviso_pendente()
    st.header("Base contábil e regras")
    pode = pode_fazer("cadastrar")
    if not pode:
        st.info("Seu papel nesta empresa permite só consultar os cadastros.")
    aba = abas(["Plano de contas", "Razão", "Regras", "Sócios", "Parâmetros"], "aba_cad")

    if aba == "Plano de contas":
        st.caption("Exporte o plano do Fortes em CSV (classificação;descrição;reduzido;...). "
                   "Conta sem código reduzido é tratada como sintética e não aceita lançamento.")
        if pode:
            f = st.file_uploader("Plano de contas do Fortes", type=["csv", "txt"], key="up_plano")
            if f and st.button("Importar plano", type="primary"):
                with tratar_erros() as _:
                    r = o.carregar_plano(c, f.name, f.getvalue())
                    st.session_state["_aviso"] = (f"Plano versão {r['versao']} importado: {r['contas']} contas, "
                                                  f"{r['analiticas']} analíticas.")
                    st.rerun()
        linhas = c.con.execute("SELECT versao, classificacao, descricao, reduzido, aceita_lancamento, natureza "
                               "FROM plano_contas WHERE vigente = 1 ORDER BY classificacao").fetchall()
        if linhas:
            st.write(f"Plano vigente: versão {linhas[0]['versao']}, {len(linhas)} contas.")
            st.dataframe(pd.DataFrame([dict(r) for r in linhas]), hide_index=True, height=360)

    if aba == "Razão":
        st.caption("O Razão serve para a conferência de saldo. Carregar um novo substitui o anterior: "
                   "use um arquivo que cubra todo o histórico da conta do banco.")
        st.warning("O leiaute de Razão do Fortes ainda não foi conferido com um arquivo real. "
                   "O formato 'lançamentos no leiaute de importação' é o único confirmado.")
        if pode:
            formato = st.radio("Formato", ["fortes_importacao", "tabular"], horizontal=True,
                               format_func={"fortes_importacao": "Lançamentos no leiaute de importação (data;D;C;valor;hist)",
                                            "tabular": "Planilha com colunas (data, conta, débito, crédito)"}.get)
            f = st.file_uploader("Arquivo do Razão", type=["csv", "txt", "xlsx"], key="up_razao")
            colunas = None
            if f and formato == "tabular":
                with tratar_erros():
                    cab, _ = ler_tabela(f.getvalue(), f.name)
                    a, b, cc, d, e = st.columns(5)
                    colunas = {"data": a.selectbox("Data", cab), "conta": b.selectbox("Conta", cab),
                               "debito": cc.selectbox("Débito", cab), "credito": d.selectbox("Crédito", cab),
                               "historico": e.selectbox("Histórico", [None] + cab)}
            if f and st.button("Carregar Razão", type="primary"):
                with tratar_erros():
                    r = o.carregar_razao(c, f.name, f.getvalue(), formato, colunas)
                    st.session_state["_aviso"] = f"Razão carregado: {r['partidas']} partidas."
                    st.rerun()
        n = c.con.execute("SELECT COUNT(*), MIN(data), MAX(data) FROM razao").fetchone()
        st.write(f"Razão atual: {n[0]} partidas" + (f", de {n[1]} a {n[2]}." if n[0] else "."))

    if aba == "Regras":
        st.caption("Regras são avaliadas por prioridade (menor primeiro); vence a primeira que casar. "
                   "Regra só propõe: alguém sempre revisa.")
        regras = c.con.execute("SELECT * FROM regras WHERE ativa = 1 ORDER BY prioridade, id").fetchall()
        if regras:
            st.dataframe(pd.DataFrame([{
                "id": r["id"], "prioridade": r["prioridade"], "nome": r["nome"], "tipo": r["tipo_padrao"],
                "padrão": r["padrao"], "sentido": r["sentido"], "contrapartida": r["conta_contrapartida"],
                "histórico": r["historico"], "natureza": r["natureza"],
                "faixa": (f"{formatar_br(r['valor_min_centavos'] or 0, False)} a "
                          f"{formatar_br(r['valor_max_centavos'], False) if r['valor_max_centavos'] else '∞'}"),
            } for r in regras]), hide_index=True)
        if pode:
            with st.form("nova_regra", clear_on_submit=True):
                st.markdown("**Nova regra**")
                a, b, cc = st.columns([2, 1, 1])
                padrao = a.text_input("Texto do histórico (sem acento, maiúsculas são ignoradas)")
                tipo = b.selectbox("Tipo", ["contem", "igual", "regex"])
                sentido = cc.selectbox("Sentido", ["saida", "entrada", "ambos"])
                conta = seletor_conta("Conta de contrapartida", "regra_conta", excluir=conta_banco_padrao())
                a, b, cc = st.columns(3)
                prioridade = a.number_input("Prioridade", 1, 9999, 100)
                natureza = b.selectbox("Natureza", o.NATUREZAS)
                nome = cc.text_input("Nome curto")
                historico = st.text_input("Histórico contábil fixo (opcional; vazio = histórico do extrato)")
                a, b = st.columns(2)
                with a:
                    vmin = campo_valor("Valor mínimo (opcional)", "rmin")
                with b:
                    vmax = campo_valor("Valor máximo (opcional)", "rmax")
                if st.form_submit_button("Criar regra"):
                    with tratar_erros("Regra criada."):
                        if not conta:
                            raise ValueError("escolha a conta de contrapartida")
                        o.criar_regra(c, nome, tipo, padrao, sentido, conta, int(prioridade), historico, natureza,
                                      abs(vmin) if vmin else None, abs(vmax) if vmax else None)
            a, b, cc = st.columns(3)
            with a:
                if regras:
                    rid = st.selectbox("Desativar regra", [r["id"] for r in regras])
                    if st.button("Desativar"):
                        with tratar_erros("Regra desativada."):
                            o.desativar_regra(c, rid)
            with b:
                fj = st.file_uploader("Importar regras (JSON)", type=["json"], key="up_regras")
                if fj and st.button("Importar regras"):
                    with tratar_erros():
                        r = o.importar_regras_json(c, fj.getvalue())
                        st.session_state["_aviso"] = (f"{r['criadas']} regra(s) importada(s)."
                                                      + (f" Ignoradas: {'; '.join(r['ignoradas'][:20])}" if r["ignoradas"] else ""))
                        st.rerun()
            with cc:
                if st.button("Reaplicar regras aos movimentos sem regra"):
                    with tratar_erros():
                        n = o.reaplicar_regras(c)
                        st.session_state["_aviso"] = f"{n} movimento(s) receberam proposta."
                        st.rerun()

    if aba == "Sócios":
        st.caption("Trechos do nome dos sócios. Movimento cujo histórico contenha um deles exige segunda confirmação.")
        termos = o.termos_socios(c.con)
        st.write(", ".join(termos) if termos else "Nenhum sócio cadastrado.")
        if pode:
            a, b = st.columns(2)
            with a:
                with st.form("socio", clear_on_submit=True):
                    t = st.text_input("Nome ou trecho do nome")
                    if st.form_submit_button("Adicionar"):
                        with tratar_erros("Sócio cadastrado."):
                            o.adicionar_socio(c, t)
            with b:
                if termos:
                    t = st.selectbox("Remover", termos)
                    if st.button("Remover sócio"):
                        with tratar_erros("Removido."):
                            o.remover_socio(c, t)

    if aba == "Parâmetros":
        st.write(f"Prefixo da marca no histórico: **{c.prefixo}** (ex.: [{c.prefixo}-202609-000123])")
        st.write(f"Limite do histórico no arquivo: **{o.limite_historico(c.con)}** caracteres")
        cb = conta_banco_padrao()
        st.write(f"Conta do banco padrão: **{opcoes_contas().get(cb, cb or 'não definida')}**")
        if pode:
            lim = o.limite_historico(c.con)
            with st.form("param"):
                pref = st.text_input("Prefixo (2 a 6 letras/números)", value=c.prefixo).strip().upper()
                conta = seletor_conta("Conta do banco padrão", "param_banco", cb)
                novo_lim = st.number_input("Limite de caracteres do histórico no arquivo do Fortes", 40, 250, lim,
                                           help="Só o arquivo exportado é cortado; o histórico completo fica guardado. "
                                                "A marca no fim nunca é cortada. Valor ainda não homologado (item H2).")
                if st.form_submit_button("Salvar parâmetros"):
                    with tratar_erros("Parâmetros salvos."):
                        if pref != c.prefixo:
                            o.definir_prefixo(c, pref)
                        if conta and conta != cb:
                            o.definir_conta_banco_padrao(c, conta)
                        if int(novo_lim) != lim:
                            o.definir_limite_historico(c, int(novo_lim))
            st.caption("Trocar o prefixo depois de exportar não afeta os lotes já gerados (a marca fica gravada).")
