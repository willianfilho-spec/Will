"""Upload de extratos e planilhas de despesas, validação e alertas de duplicidade."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from domain import operacoes as o
from domain.money import formatar_br
from parsers.tabular_parser import Mapeamento, ler_tabela, sugerir_mapeamento
from ui.comum import abas, aviso_pendente, conta_banco_padrao, exigir_contexto, pode_fazer, seletor_conta, tratar_erros


def _mapeamento(f, chave: str, despesas: bool = False) -> Mapeamento | None:
    try:
        cab, linhas = ler_tabela(f.getvalue(), f.name)
    except Exception as exc:  # erro estrutural: mostrado pelo tratar_erros na carga
        st.error(str(exc))
        return None
    st.dataframe(pd.DataFrame(linhas[:8]), hide_index=True)
    s = sugerir_mapeamento(cab)
    opc = [None] + cab
    fmt = lambda c: "(nenhuma)" if c is None else c  # noqa: E731
    idx = lambda k: opc.index(s[k]) if s.get(k) in opc else 0  # noqa: E731
    a, b = st.columns(2)
    data = a.selectbox("Coluna da data", cab, index=cab.index(s["data"]) if s["data"] in cab else 0, key=f"{chave}d")
    hist = b.selectbox("Coluna do histórico/descrição", cab,
                       index=cab.index(s["historico"]) if s["historico"] in cab else 0, key=f"{chave}h")
    modo = st.radio("Valores", ["uma coluna com sinal", "colunas de entrada e saída"], horizontal=True, key=f"{chave}m")
    valor = entrada = saida = None
    if modo == "uma coluna com sinal":
        valor = st.selectbox("Coluna do valor", cab, index=cab.index(s["valor"]) if s["valor"] in cab else 0,
                             key=f"{chave}v")
    else:
        a, b = st.columns(2)
        entrada = a.selectbox("Coluna de entrada/crédito", opc, index=idx("entrada"), key=f"{chave}e", format_func=fmt)
        saida = b.selectbox("Coluna de saída/débito", opc, index=idx("saida"), key=f"{chave}s", format_func=fmt)
    doc = st.selectbox("Coluna de documento/lançamento bancário (opcional)", opc, index=idx("documento"), key=f"{chave}doc",
                       format_func=fmt)
    inverter = st.checkbox("Os pagamentos vêm positivos (inverter o sinal)", value=despesas, key=f"{chave}i")
    return Mapeamento(data=data, historico=hist, valor=valor, entrada=entrada, saida=saida, documento=doc,
                      inverter_sinal=inverter)


def render() -> None:
    c = exigir_contexto()
    aviso_pendente()
    st.header("Carga e validação de movimentos")
    if not pode_fazer("carregar"):
        st.info("Seu papel não permite carregar arquivos nesta empresa.")
        return
    aba = abas(["Extrato bancário", "Planilha de despesas", "Arquivos carregados"], "aba_carga")
    if aba == "Extrato bancário":
        st.caption("OFX, CSV ou XLSX. Erro de data ou valor recusa o arquivo inteiro. "
                   "Arquivo idêntico a um já carregado (SHA-256) é bloqueado; possíveis duplicidades vão para a fila de decisão.")
        conta = seletor_conta("Conta do banco no plano (reduzido)", "carga_conta", conta_banco_padrao())
        f = st.file_uploader("Extrato", type=["ofx", "csv", "txt", "xlsx"], key="up_extrato")
        mapa = None
        if f and not f.name.lower().endswith(".ofx"):
            mapa = _mapeamento(f, "ext")
        if f and conta and st.button("Validar e carregar extrato", type="primary"):
            with tratar_erros():
                r = o.carregar_extrato(c, f.name, f.getvalue(), conta, mapa)
                msg = (f"{r['movimentos']} movimentos de {r['periodo'][0]} a {r['periodo'][1]}: "
                       f"{r['propostos']} com proposta de regra, {r['alertas_duplicidade']} alerta(s) de duplicidade, "
                       f"{r['segunda_revisao']} exigem segunda confirmação.")
                if r["saldo_final_ofx"] is not None:
                    msg += f" Saldo informado no OFX: {formatar_br(r['saldo_final_ofx'])} em {r['saldo_data_ofx']}."
                st.session_state["_aviso"] = msg
                st.rerun()
    if aba == "Planilha de despesas":
        st.caption("A planilha não gera lançamento. Ela serve de pista para identificar pagamentos sem nome "
                   "(SISPAG, PIX QR) pelo valor e pela data, na fila de classificação.")
        f = st.file_uploader("Planilha de despesas", type=["csv", "txt", "xlsx"], key="up_desp")
        if f:
            mapa = _mapeamento(f, "desp", despesas=True)
            if mapa and st.button("Validar e carregar planilha", type="primary"):
                with tratar_erros():
                    r = o.carregar_planilha_despesas(c, f.name, f.getvalue(), mapa)
                    st.session_state["_aviso"] = f"{r['itens']} despesas carregadas."
                    st.rerun()
    if aba == "Arquivos carregados":
        arqs = c.con.execute("SELECT a.id, a.nome_original, a.tipo, a.status, a.enviado_por, a.enviado_em, a.sha256, "
                             "(SELECT COUNT(*) FROM movimentos m WHERE m.arquivo_id = a.id) movimentos "
                             "FROM arquivos a ORDER BY a.id DESC").fetchall()
        st.dataframe(pd.DataFrame([dict(r) for r in arqs]), hide_index=True)
        st.caption("Os originais ficam em arquivos/originais com nome UUID e só leitura.")
