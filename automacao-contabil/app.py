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


def texto_literal(texto: str) -> str:
    """Impede que o histórico do banco seja interpretado como Markdown/LaTeX.

    Sem isto, "US$ 10 ... US$ 20" vira fórmula e "*PIX*" vira itálico.
    """
    return "".join("\\" + c if c in "\\`*_{}[]()<>#+-.!|$~" else c for c in texto)


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


def registrar_download(caminho: str, responsavel: str, lote_id: int) -> None:
    # Callbacks do Streamlit rodam em outra thread; o SQLite exige conexão própria.
    banco = BancoDeDados(caminho)
    try:
        banco.registrar_evento(responsavel, "arquivo_baixado", f"lote {lote_id}", lote_id=lote_id)
        banco.conexao.commit()
    finally:
        banco.fechar()


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
arquivo = col1.file_uploader("Extrato OFX, CSV ou planilha XLSX", type=["ofx", "ofc", "csv", "txt", "xlsx"])
conta_bancaria = col2.text_input("Conta bancária (obrigatória para CSV e XLSX)", "")
if arquivo and st.button("Processar extrato", type="primary"):
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / Path(arquivo.name).name  # só o nome, nunca um caminho
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
            f"**{texto_literal(item['historico_banco'])}**"
            + (f" · {texto_literal(item['favorecido'])}" if item.get("favorecido") else "")
            + "  \n"
            f"{data_br(item['data'])} · {texto_literal(item['origem'])} linha {item['linha']}"
        )
        b.markdown(f"**{brl(item['valor'])}**")
        c.markdown(f"D: `{item['conta_debito'] or '-'}`  \nC: `{item['conta_credito'] or '-'}`")
        if item["motivos"]:
            st.caption(texto_literal(item["motivos"]))
        if filtro in ("pendente", "bloqueado", "liberado"):
            atual = item["conta_contrapartida"]
            x, y, z = st.columns([4, 1, 2])
            escolhida = x.selectbox(
                "Contrapartida", contas,
                index=contas.index(atual) if atual in contas else None,
                format_func=lambda k: rotulos[k], key=f"conta-{item['chave']}",
                placeholder="Escolha a conta",
            )
            if y.button("Aprovar", key=f"ok-{item['chave']}", disabled=escolhida is None):
                try:
                    motor.aprovar(item["chave"], escolhida if escolhida != atual else None)
                    st.rerun()
                except (ValueError, KeyError) as erro:
                    st.error(f"Não foi possível aprovar: {erro}")
            motivo = z.text_input("Motivo do descarte", key=f"mot-{item['chave']}")
            if z.button("Descartar", key=f"x-{item['chave']}", disabled=not motivo.strip()):
                try:
                    motor.descartar(item["chave"], motivo)
                    st.rerun()
                except (ValueError, KeyError) as erro:
                    st.error(f"Não foi possível descartar: {erro}")

# ------------------------------------------------------------------ exportar
st.subheader("3. Exportar liberados")
st.caption(
    "Leiaute provisório (CSV genérico). Ainda não corresponde ao leiaute de nenhum "
    "sistema contábil específico."
)
if st.button("Gerar arquivo de importação", disabled=contagem[Status.LIBERADO] == 0):
    with tempfile.TemporaryDirectory() as pasta:
        lote, n = motor.exportar(Path(pasta) / "lancamentos.csv")
    if n:
        st.session_state["aviso_exportacao"] = f"Lote {lote} gerado com {n} lançamentos."
    # Recarrega para os contadores e a lista refletirem a exportação.
    st.rerun()
if aviso := st.session_state.pop("aviso_exportacao", None):
    st.success(aviso)

# O arquivo de cada lote é regerado a partir do banco de dados. Assim, se a
# página for fechada antes do download, o arquivo não se perde, e os
# lançamentos continuam protegidos contra uma segunda exportação.
lotes = motor.lotes_exportacao()
if lotes:
    st.markdown("**Arquivos gerados**")
for lote in lotes[:10]:
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / "lote.csv"
        motor.reexportar(lote["id"], destino, registrar=False)
        dados = destino.read_bytes()
    st.download_button(
        f"Baixar lote {lote['id']} · {lote['quantidade']} lançamentos · "
        f"{lote['criado_em'].replace('T', ' ')} · {lote['usuario']}",
        dados,
        file_name=f"lancamentos_lote_{lote['id']}.csv",
        mime="text/csv",
        key=f"lote-{lote['id']}",
        on_click=registrar_download,
        args=(caminho_db, usuario, lote["id"]),
    )
