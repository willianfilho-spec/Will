"""Interface local de conferência (Streamlit).

    streamlit run app.py

Roda na máquina do escritório. Nenhum dado sai do computador, a não ser que a
opção de sugestão por IA seja ligada na barra lateral.
"""

from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import streamlit as st

from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas, Status

EXEMPLOS = Path(__file__).parent / "exemplos"


def brl(valor: str) -> str:
    v = Decimal(valor)
    texto = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {texto}"


def data_br(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")

st.set_page_config(page_title="Conferência de lançamentos", layout="wide")
st.title("Conferência de lançamentos")
st.caption("Prova de conceito. Os lançamentos só saem do sistema depois de liberados.")

with st.sidebar:
    st.header("Configuração")
    caminho_db = st.text_input("Banco de dados", "motor_contabil.db")
    caminho_plano = st.text_input("Plano de contas (CSV)", str(EXEMPLOS / "plano_contas.csv"))
    caminho_regras = st.text_input("Regras (JSON)", str(EXEMPLOS / "regras.json"))
    usuario = st.text_input("Responsável pela revisão", "operador")
    usar_ia = st.checkbox(
        "Sugerir contas com IA",
        value=False,
        help="Envia apenas o histórico (CPF/CNPJ mascarados) e o sentido da operação. "
        "Toda sugestão fica pendente de aprovação.",
    )


def obter_motor() -> Motor:
    classificador = None
    if usar_ia:
        from motor_contabil.classificador_ia import ClassificadorClaude

        classificador = ClassificadorClaude()
    return Motor(
        BancoDeDados(caminho_db),
        PlanoDeContas.carregar(caminho_plano),
        ConjuntoDeRegras.carregar(caminho_regras),
        classificador=classificador,
        usuario=usuario,
    )


try:
    motor = obter_motor()
except Exception as erro:  # configuração inválida: mostrar e parar
    st.error(f"Não foi possível carregar a configuração: {erro}")
    st.stop()

# ------------------------------------------------------------------ importar
st.subheader("1. Importar extrato")
col1, col2 = st.columns([3, 2])
arquivo = col1.file_uploader("Extrato OFX ou CSV", type=["ofx", "ofc", "csv", "txt"])
conta_bancaria = col2.text_input("Conta bancária (obrigatória para CSV)", "")
if arquivo and st.button("Processar extrato", type="primary"):
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / arquivo.name
        destino.write_bytes(arquivo.getvalue())
        try:
            resultado = motor.importar(destino, conta_bancaria or None)
            st.success("Extrato processado.")
            st.code(resultado.resumo(), language=None)
        except Exception as erro:
            st.error(f"Erro ao processar: {erro}")

# ------------------------------------------------------------------ conferir
st.subheader("2. Conferir")
todos = motor.listar()
contagem = {s: sum(1 for i in todos if i["status"] == s.value) for s in Status}
m = st.columns(4)
m[0].metric("Liberados", contagem[Status.LIBERADO])
m[1].metric("Pendentes", contagem[Status.PENDENTE])
m[2].metric("Bloqueados", contagem[Status.BLOQUEADO])
m[3].metric("Exportados", contagem[Status.EXPORTADO])

filtro = st.radio(
    "Mostrar", ["pendente", "bloqueado", "liberado", "exportado", "descartado"], horizontal=True
)
itens = [i for i in todos if i["status"] == filtro]
contas = [c.codigo for c in motor.plano.analiticas()]
rotulos = {c.codigo: f"{c.codigo} - {c.descricao}" for c in motor.plano.analiticas()}

if not itens:
    st.info("Nenhum lançamento nesta situação.")
for item in itens:
    with st.container(border=True):
        a, b, c = st.columns([4, 2, 2])
        a.markdown(
            f"**{item['historico_banco']}**  \n"
            f"{data_br(item['data'])} · {item['origem']} linha {item['linha']}"
        )
        b.markdown(f"**{brl(item['valor'])}**")
        c.markdown(f"D: `{item['conta_debito'] or '-'}`  \nC: `{item['conta_credito'] or '-'}`")
        if item["motivos"]:
            st.caption(item["motivos"])
        if filtro in ("pendente", "bloqueado", "liberado"):
            atual = item["conta_contrapartida"]
            x, y, z = st.columns([4, 1, 2])
            escolhida = x.selectbox(
                "Contrapartida", contas,
                index=contas.index(atual) if atual in contas else None,
                format_func=lambda k: rotulos[k], key=f"conta-{item['chave']}",
            )
            if y.button("Aprovar", key=f"ok-{item['chave']}", disabled=escolhida is None):
                lanc = motor.aprovar(item["chave"], escolhida if escolhida != atual else None)
                st.toast(f"Resultado: {lanc.status.value}")
                st.rerun()
            motivo = z.text_input("Motivo do descarte", key=f"mot-{item['chave']}")
            if z.button("Descartar", key=f"x-{item['chave']}", disabled=not motivo.strip()):
                motor.descartar(item["chave"], motivo)
                st.rerun()

# ------------------------------------------------------------------ exportar
st.subheader("3. Exportar liberados")
st.caption(
    "Leiaute provisório (CSV genérico). Ainda não corresponde ao leiaute de nenhum "
    "sistema contábil específico."
)
if st.button("Gerar arquivo de importação", disabled=contagem[Status.LIBERADO] == 0):
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / "lancamentos.csv"
        lote, n = motor.exportar(destino)
        st.session_state["exportacao"] = (f"lancamentos_lote_{lote}.csv", destino.read_bytes(), n)
if "exportacao" in st.session_state:
    nome, dados, n = st.session_state["exportacao"]
    st.download_button(f"Baixar {nome} ({n} lançamentos)", dados, file_name=nome, mime="text/csv")
