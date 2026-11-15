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

from motor_contabil import (
    BancoDeDados, ConjuntoDeRegras, ExportadorFortes, Motor, PlanoDeContas, Status,
)
from motor_contabil.conciliacao import confrontar, ler_importados, resumo_mensal

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
    formato_plano = st.radio(
        "Formato do plano", ["Exemplo do motor", "Exportado do Fortes"], horizontal=True,
        help="O plano exportado do Fortes já traz o código reduzido de cada conta.",
    )
    leiaute = st.radio("Leiaute de exportação", ["Fortes", "CSV genérico"], horizontal=True)
    prefixo_marca = st.text_input("Prefixo da marca no histórico (Fortes)", "EXT", max_chars=6)
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
    if formato_plano == "Exportado do Fortes":
        plano = PlanoDeContas.carregar_fortes(caminho_plano)
    else:
        plano = PlanoDeContas.carregar(caminho_plano)
    regras = ConjuntoDeRegras.carregar(caminho_regras)
    banco = BancoDeDados(caminho_db)
    try:
        return Motor(banco, plano, regras, classificador=classificador, usuario=usuario)
    except Exception:
        banco.fechar()
        raise


try:
    motor = obter_motor()
except Exception as erro:  # configuração inválida: mostrar e parar
    st.error(f"Não foi possível carregar a configuração: {erro}")
    st.stop()

try:
    # ------------------------------------------------------------------ importar
    st.subheader("1. Importar extrato")
    col1, col2 = st.columns([3, 2])
    arquivo = col1.file_uploader(
        "Extrato OFX, CSV ou planilha XLSX", type=["ofx", "ofc", "csv", "txt", "xlsx"]
    )
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
                f"**{texto_literal(item['historico_banco'])}**  \n"
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
        try:
            with tempfile.TemporaryDirectory() as pasta:
                exportador = (
                    ExportadorFortes(motor.plano, prefixo_marca.strip().upper() or "EXT")
                    if leiaute == "Fortes" else None
                )
                lote, n = motor.exportar(Path(pasta) / "lancamentos.csv", exportador)
            if n:
                st.session_state["aviso_exportacao"] = f"Lote {lote} gerado com {n} lançamentos."
            st.rerun()
        except Exception as erro:
            st.error(f"Não foi possível exportar. Confira o banco e o espaço em disco: {erro}")
    if aviso := st.session_state.pop("aviso_exportacao", None):
        st.success(aviso)

    # Os bytes originais de cada lote são recuperados do banco de dados. Assim, se a
    # página for fechada antes do download, o arquivo não se perde, e os
    # lançamentos continuam protegidos contra uma segunda exportação.
    lotes = motor.lotes_exportacao()
    if lotes:
        st.markdown("**Arquivos gerados**")
    for lote in lotes:
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "lote.csv"
            try:
                motor.reexportar(lote["id"], destino, registrar=False)
                dados = destino.read_bytes()
            except (OSError, ValueError, KeyError) as erro:
                st.error(f"Não foi possível recuperar o lote {lote['id']}: {erro}")
                continue
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

    # ------------------------------------------------------------------ conferir o banco
    st.subheader("4. Conferir o banco: extrato x contabilidade")
    st.caption(
        "Compara o extrato completo com os arquivos já importados no Fortes: saldo em cada "
        "fim de mês e movimento a movimento. Só o extrato completo (com entradas e saldos) "
        "permite essa conferência; a planilha de despesas não."
    )
    c1, c2, c3 = st.columns([3, 3, 1])
    extrato_pdf = c1.file_uploader("Extrato Itaú em PDF", type=["pdf"], key="conf-extrato")
    importados = c2.file_uploader(
        "Arquivos já importados no Fortes", type=["csv", "txt"], accept_multiple_files=True,
        key="conf-importados",
    )
    reduzido_banco = c3.text_input("Reduzido do banco", "")
    if extrato_pdf and importados and reduzido_banco and st.button("Conferir"):
        from motor_contabil.leitores import ler_itau_pdf_completo

        try:
            with tempfile.TemporaryDirectory() as pasta:
                caminho_pdf = Path(pasta) / Path(extrato_pdf.name).name
                caminho_pdf.write_bytes(extrato_pdf.getvalue())
                extrato = ler_itau_pdf_completo(caminho_pdf, reduzido_banco.strip())
                aceitos = []
                for arquivo_imp in importados:
                    caminho_imp = Path(pasta) / Path(arquivo_imp.name).name
                    caminho_imp.write_bytes(arquivo_imp.getvalue())
                    aceitos += ler_importados(caminho_imp)
            linhas = resumo_mensal(extrato.transacoes, extrato.saldos, aceitos, reduzido_banco.strip())
            total = confrontar(extrato.transacoes, aceitos, reduzido_banco.strip())
            st.write(
                f"{len(extrato.transacoes)} movimentos no extrato; {extrato.dias_conferidos} saldos "
                "diários conferidos com a soma dos movimentos."
            )
            st.dataframe(
                [{"Mês": l.mes, "Fim": data_br(l.fim.isoformat()),
                  "Extrato": brl(str(l.saldo_extrato)), "Contábil": brl(str(l.saldo_contabil)),
                  "Diferença": brl(str(l.diferenca)), "Só no extrato": l.so_extrato,
                  "Só na contabilidade": l.so_contabil} for l in linhas],
                hide_index=True, use_container_width=True,
            )
            if all(l.diferenca == 0 for l in linhas) and not total.so_no_extrato \
                    and not total.so_na_contabilidade:
                st.success(f"Conciliado: {total.pareados} movimentos pareados, saldo igual em todos os meses.")
            else:
                st.error("Não conciliado. Movimentos sem par abaixo.")
                st.dataframe(
                    [{"Lado": "só no extrato", "Data": data_br(x.data.isoformat()),
                      "Valor": brl(str(x.valor)), "Histórico": x.historico}
                     for x in total.so_no_extrato]
                    + [{"Lado": "só na contabilidade", "Data": data_br(x.data.isoformat()),
                        "Valor": brl(str(x.valor)), "Histórico": f"{x.historico} ({x.origem}:{x.linha})"}
                       for x in total.so_na_contabilidade],
                    hide_index=True, use_container_width=True,
                )
        except Exception as erro:
            st.error(f"Não foi possível conferir: {erro}")

finally:
    motor.banco.fechar()
