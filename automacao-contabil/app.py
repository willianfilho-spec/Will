"""Interface local de conferência (Streamlit).

    streamlit run app.py

Roda na máquina do escritório. Nenhum dado sai do computador, a não ser que a
opção de sugestão por IA seja ligada na barra lateral. Cada empresa tem a sua
pasta dentro da pasta de dados (ver motor_contabil/empresas.py).
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import streamlit as st

from motor_contabil import BancoDeDados, ExportadorFortes, Motor, Status
from motor_contabil import empresas
from motor_contabil.conciliacao import confrontar, ler_importados, resumo_mensal
from motor_contabil.tela_importacao import (
    EXTENSOES_ACEITAS, TAMANHO_MAXIMO, RelatorioImportacao, formatar_moeda, processar_importacao,
)


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
    pasta_dados = Path(st.text_input(
        "Pasta de dados do escritório", os.environ.get("MOTOR_CONTABIL_DADOS", "dados")
    ))
    try:
        cadastradas = empresas.listar(pasta_dados)
    except ValueError as erro:
        st.error(str(erro))
        st.stop()
    with st.expander("Cadastrar empresa", expanded=not cadastradas):
        with st.form("cadastro", clear_on_submit=False):
            novo_id = st.text_input("Identificador (pasta)", help="Ex.: nx. Letras minúsculas, números e hífen.")
            novo_nome = st.text_input("Razão social")
            novo_cnpj = st.text_input("CNPJ")
            nova_conta = st.text_input("Conta bancária", help="Como o banco é identificado nos extratos; para o Fortes, o reduzido (ex.: 362).")
            novo_prefixo = st.text_input("Prefixo da marca no histórico", max_chars=6, help="Ex.: NX")
            novo_formato = st.radio("Plano de contas", ["Exportado do Fortes", "Exemplo do motor"], horizontal=True)
            novo_plano = st.file_uploader("Plano de contas (CSV)", type=["csv", "txt"])
            novas_regras = st.file_uploader("Regras (JSON)", type=["json"])
            if st.form_submit_button("Cadastrar"):
                if not (novo_plano and novas_regras):
                    st.error("Envie o plano de contas e as regras.")
                else:
                    with tempfile.TemporaryDirectory() as pasta:
                        caminho_p = Path(pasta) / "plano.csv"
                        caminho_r = Path(pasta) / "regras.json"
                        caminho_p.write_bytes(novo_plano.getvalue())
                        caminho_r.write_bytes(novas_regras.getvalue())
                        try:
                            empresas.cadastrar(
                                pasta_dados, novo_id.strip(), novo_nome, novo_cnpj, nova_conta,
                                novo_prefixo.strip().upper(),
                                "fortes" if novo_formato == "Exportado do Fortes" else "motor",
                                caminho_p, caminho_r,
                            )
                            st.success("Empresa cadastrada.")
                            st.rerun()
                        except ValueError as erro:
                            st.error(f"Não foi possível cadastrar: {erro}")
    if not cadastradas:
        st.info("Cadastre a primeira empresa para começar.")
        st.stop()
    empresa = st.selectbox(
        "Empresa", cadastradas, format_func=lambda e: f"{e.nome} ({e.identificador})"
    )
    st.caption(f"CNPJ {empresa.cnpj} · conta {empresa.conta_bancaria} · marca {empresa.prefixo_marca}")
    leiaute = st.radio("Leiaute de exportação", ["Fortes", "CSV genérico"], horizontal=True)
    usuario = st.text_input("Responsável pela revisão", "operador")
    pasta_backup = st.text_input("Pasta de backup (para o aviso de cópia atrasada)", "")
    if pasta_backup.strip():
        from motor_contabil.backup import horas_desde_ultima

        horas = horas_desde_ultima(pasta_backup.strip())
        if horas is None:
            st.error("Nenhuma cópia de segurança encontrada nessa pasta.")
        elif horas > 26:
            st.error(f"Última cópia de segurança há {horas:.0f} horas. Confira o agendamento.")
        else:
            st.caption(f"Última cópia de segurança há {horas:.1f} horas.")
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
    return empresa.abrir_motor(usuario, classificador)


caminho_db = str(empresa.caminho_banco)
try:
    motor = obter_motor()
except Exception as erro:  # configuração inválida: mostrar e parar
    st.error(f"Não foi possível carregar a configuração: {erro}")
    st.stop()

try:
    # ------------------------------------------------------------------ importar
    st.subheader(f"1. Importar extrato · {empresa.nome}")
    chave_relatorio = f"relatorio_importacao_{empresa.identificador}"
    arquivo = st.file_uploader(
        "Extrato OFX, CSV, planilha XLSX ou extrato Itaú em PDF",
        type=[e.lstrip(".") for e in EXTENSOES_ACEITAS],
        help="Formatos aceitos: OFX/OFC (o melhor, baixado no internet banking), CSV/TXT com cabeçalho "
        "(colunas data, histórico e valor), XLSX com uma única planilha e PDF do Itaú no modelo "
        f"Entradas e Saídas. Tamanho máximo: {TAMANHO_MAXIMO // (1024 * 1024)} MB.",
    )
    if arquivo:
        conteudo = arquivo.getvalue()
        if outras := empresas.empresas_com_o_arquivo(pasta_dados, conteudo, empresa.identificador):
            st.warning(
                f"Este mesmo arquivo já foi recebido na empresa {', '.join(outras)}. "
                f"Confira se ele é mesmo de {empresa.nome} antes de processar."
            )
    if arquivo and st.button("Processar extrato", type="primary"):
        st.session_state[chave_relatorio] = processar_importacao(
            motor, empresa, arquivo.name, arquivo.getvalue()
        )

    relatorio: RelatorioImportacao | None = st.session_state.get(chave_relatorio)
    if relatorio is not None:
        if relatorio.ok:
            st.success(relatorio.titulo)
            st.write(relatorio.detalhe)
            m1 = st.columns(6)
            m1[0].metric("Lidas", relatorio.lidas)
            m1[1].metric("Novas", relatorio.novas)
            m1[2].metric("Já importadas", relatorio.ja_importadas)
            m1[3].metric("Liberados", relatorio.liberados)
            m1[4].metric("Pendentes", relatorio.pendentes)
            m1[5].metric("Bloqueados", relatorio.bloqueados)
            m2 = st.columns(2)
            m2[0].metric("Entradas no arquivo", formatar_moeda(relatorio.total_entradas))
            m2[1].metric("Saídas no arquivo", formatar_moeda(relatorio.total_saidas))
            if relatorio.primeira_data and relatorio.ultima_data:
                st.write(
                    f"Período: de {relatorio.primeira_data.strftime('%d/%m/%Y')} "
                    f"a {relatorio.ultima_data.strftime('%d/%m/%Y')}"
                )
            for aviso in relatorio.avisos:
                st.warning(f"Atenção: {aviso}")
            if relatorio.o_que_fazer:
                st.info(f"O que fazer: {relatorio.o_que_fazer}")
        else:
            st.error(f"{relatorio.titulo}. {relatorio.detalhe}")
            st.info(f"O que fazer: {relatorio.o_que_fazer}")

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
                    ExportadorFortes(motor.plano, empresa.prefixo_marca)
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
    c1, c2 = st.columns(2)
    extrato_pdf = c1.file_uploader("Extrato Itaú em PDF", type=["pdf"], key="conf-extrato")
    importados = c2.file_uploader(
        "Arquivos já importados no Fortes", type=["csv", "txt"], accept_multiple_files=True,
        key="conf-importados",
    )
    reduzido_banco = empresa.conta_bancaria
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
