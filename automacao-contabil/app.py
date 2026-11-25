"""Interface local de conferência (Streamlit).

    streamlit run app.py

Roda na máquina do escritório. Nenhum dado sai do computador, a não ser que a
opção de sugestão por IA seja ligada na barra lateral. Cada empresa tem a sua
pasta dentro da pasta de dados (ver motor_contabil/empresas.py).
"""

from __future__ import annotations

import calendar
import html
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import streamlit as st

from motor_contabil import BancoDeDados, ExportadorFortes, Motor, Status
from motor_contabil import empresas
from motor_contabil.conciliacao import Confronto, LinhaMensal, confrontar, ler_importados, resumo_mensal
from motor_contabil import acesso, relatorios
from motor_contabil.tela_importacao import (
    EXTENSOES_ACEITAS, TAMANHO_MAXIMO, RelatorioImportacao, formatar_moeda, processar_importacao,
)
from motor_contabil.texto import normalizar


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


ESTADOS_VISUAIS = {
    Status.LIBERADO: ("✓", "Liberado"),
    Status.PENDENTE: ("◷", "Pendente"),
    Status.BLOQUEADO: ("!", "Bloqueado"),
    Status.EXPORTADO: ("↗", "Exportado"),
    Status.DESCARTADO: ("×", "Descartado"),
}

ITENS_POR_PAGINA = 20


@dataclass(frozen=True)
class ConferenciaExibida:
    extrato: str
    importados: tuple[str, ...]
    movimentos: int
    dias_conferidos: int
    linhas: list[LinhaMensal]
    confronto: Confronto


def painel_inicial(nome: str, itens: list[dict], contagem: dict[Status, int]) -> str:
    em_revisao = contagem[Status.PENDENTE] + contagem[Status.BLOQUEADO]
    ultimo = data_br(itens[-1]["data"]) if itens else "Sem movimentos"
    if em_revisao:
        destino, acao = "revisar-lancamentos", "Revisar lançamentos"
        orientacao = "Confira os movimentos que precisam de uma decisão antes de exportar."
    elif contagem[Status.LIBERADO]:
        destino, acao = "exportar-fortes", "Preparar arquivo para o Fortes"
        orientacao = "Há lançamentos liberados para gerar um arquivo de importação."
    elif contagem[Status.EXPORTADO]:
        destino, acao = "conferir-banco", "Conferir o banco"
        orientacao = "Após importar o lote no Fortes, confira os saldos e os movimentos."
    else:
        destino, acao = "importar-extrato", "Importar um extrato"
        orientacao = "Escolha a empresa na barra lateral e carregue um arquivo para começar."
    return f"""
    <section class="cf-inicio" aria-labelledby="titulo-painel">
      <div class="cf-inicio-conteudo">
        <p class="cf-empresa">{html.escape(nome)}</p>
        <h2 id="titulo-painel">Conciliação bancária<br>e revisão contábil</h2>
        <p>{orientacao}</p>
        <div class="cf-acoes">
          <a class="cf-acao" href="#{destino}">{acao}</a>
          <a class="cf-acao-secundaria" href="#como-comecar">Como começar</a>
        </div>
      </div>
      <div class="cf-visao">
        <h3>Andamento da empresa</h3>
        <dl>
          <div><dt>Movimentos processados</dt><dd>{len(itens)}</dd></div>
          <div><dt>Em revisão ou bloqueados</dt><dd>{em_revisao}</dd></div>
          <div><dt>Último movimento</dt><dd>{ultimo}</dd></div>
        </dl>
      </div>
    </section>
    """


def corresponde_busca(item: dict, consulta: str) -> bool:
    campos = ("historico_banco", "chave", "conta_contrapartida", "conta_debito", "conta_credito")
    return any(consulta in normalizar(item[campo] or "") for campo in campos)


def reiniciar_pagina(chave: str) -> None:
    st.session_state[chave] = 1


def mostrar_conferencia(resultado: ConferenciaExibida) -> None:
    linhas, total = resultado.linhas, resultado.confronto
    extrato = texto_literal(resultado.extrato)
    importados = ", ".join(map(texto_literal, resultado.importados))
    st.caption(
        f"Extrato: {extrato} · Arquivos importados: {importados}"
    )
    movimentos = "movimento" if resultado.movimentos == 1 else "movimentos"
    saldos = "saldo diário conferido" if resultado.dias_conferidos == 1 else "saldos diários conferidos"
    st.write(f"{resultado.movimentos} {movimentos} no extrato e {resultado.dias_conferidos} {saldos}.")
    st.dataframe(
        [{"Mês": l.mes, "Fim": data_br(l.fim.isoformat()),
          "Extrato": brl(str(l.saldo_extrato)), "Contábil": brl(str(l.saldo_contabil)),
          "Diferença": brl(str(l.diferenca)), "Só no extrato": l.so_extrato,
          "Só na contabilidade": l.so_contabil} for l in linhas],
        hide_index=True, width="stretch",
    )
    if all(l.diferenca == 0 for l in linhas) and not total.so_no_extrato and not total.so_na_contabilidade:
        pareados = "movimento pareado" if total.pareados == 1 else "movimentos pareados"
        st.success(f"Conciliado: {total.pareados} {pareados} e saldos iguais nos meses conferidos.")
        return
    if not (total.so_no_extrato or total.so_na_contabilidade):
        st.error("Não conciliado. Confira as diferenças de saldo na tabela.")
        return
    st.error(
        "Há diferenças. Confira os valores e as datas na tabela. "
        "Procure os movimentos que aparecem só no extrato ou só nos arquivos do Fortes."
    )
    st.dataframe(
        [{"Lado": "Só no extrato", "Data": data_br(x.data.isoformat()),
          "Valor": brl(str(x.valor)), "Histórico": x.historico} for x in total.so_no_extrato]
        + [{"Lado": "Só na contabilidade", "Data": data_br(x.data.isoformat()),
            "Valor": brl(str(x.valor)), "Histórico": f"{x.historico} ({x.origem}:{x.linha})"}
           for x in total.so_na_contabilidade],
        hide_index=True, width="stretch",
    )


st.set_page_config(page_title="Conciliador Fortes", layout="wide")
interface = Path(__file__).resolve().parent / "interface"
st.html(interface / "design.css")
st.html(interface / "tema.html", unsafe_allow_javascript=True)
# Quem está usando: login Google pelo Cloudflare Access (acesso remoto) ou nome
# digitado (acesso no próprio computador). Ver motor_contabil/acesso.py.
try:
    config_acesso = acesso.carregar_config(os.environ.get("MOTOR_CONTABIL_ACESSO"))
    identidade = acesso.identificar(dict(st.context.headers), config_acesso)
except (ValueError, acesso.AcessoNegado) as erro:
    st.title("Conciliador Fortes")
    st.error(str(erro))
    st.stop()
remoto = identidade is not None
treinamento = os.environ.get("MOTOR_CONTABIL_TREINAMENTO") == "1"

st.title("Conciliador Fortes")
if treinamento:
    st.info("Ambiente de treinamento. Use apenas arquivos e dados fictícios.")
aviso_cadastro = st.empty()

with st.sidebar:
    # A ordem na tela segue o uso: primeiro o que muda todo dia, depois o que
    # se configura uma vez. Os blocos são preenchidos fora dessa ordem porque a
    # lista de empresas depende da pasta de dados.
    bloco_empresa = st.container()
    bloco_cadastro = st.container()
    if remoto:
        # Pelo acesso remoto, pastas e IA ficam como foram configuradas no
        # computador do escritório e não podem ser trocadas pela tela.
        pasta_dados = Path(os.environ.get("MOTOR_CONTABIL_DADOS", "dados"))
        pasta_backup = os.environ.get("MOTOR_CONTABIL_BACKUP", "")
        usar_ia = False
    else:
        with st.expander("Configurações deste computador"):
            pasta_dados = Path(st.text_input(
                "Pasta de dados do escritório", os.environ.get("MOTOR_CONTABIL_DADOS", "dados")
            ))
            pasta_backup = st.text_input(
                "Pasta de backup",
                os.environ.get("MOTOR_CONTABIL_BACKUP", ""),
                help="Usada só para avisar quando a última cópia de segurança estiver atrasada.",
            )
            usar_ia = st.checkbox(
                "Sugerir contas com IA",
                value=False,
                help="Envia apenas o histórico (CPF/CNPJ mascarados) e o sentido da operação. "
                "Toda sugestão fica pendente de aprovação.",
            )

    try:
        cadastradas = empresas.listar(pasta_dados)
    except ValueError as erro:
        bloco_empresa.error(str(erro))
        st.stop()

    with bloco_cadastro.expander("Cadastrar empresa", expanded=not cadastradas):
        with st.form("cadastro", clear_on_submit=False):
            novo_id = st.text_input("Identificador (pasta)", help="Ex.: nx. Letras minúsculas, números e hífen.")
            novo_nome = st.text_input("Razão social")
            novo_cnpj = st.text_input("CNPJ")
            nova_conta = st.text_input("Conta bancária", help="Como o banco é identificado nos extratos; para o Fortes, o reduzido (ex.: 362).")
            novo_prefixo = st.text_input("Prefixo da marca no histórico", max_chars=6, help="Ex.: NX")
            novo_formato = st.radio("Plano de contas", ["Exportado do Fortes", "Exemplo do motor"], horizontal=True)
            novo_plano = st.file_uploader("Plano de contas (CSV)", type=["csv", "txt"])
            novas_regras = st.file_uploader("Regras (JSON)", type=["json"])
            if st.form_submit_button("Cadastrar empresa", type="primary"):
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
        aviso_cadastro.info("Cadastre a primeira empresa na barra lateral para começar.")
        st.stop()

    with bloco_empresa:
        empresa = st.selectbox(
            "Empresa", cadastradas, format_func=lambda e: f"{e.nome} ({e.identificador})",
            help="Escolha a empresa antes de importar, revisar ou gerar arquivos.",
        )
        st.caption(f"CNPJ {empresa.cnpj} · banco {empresa.conta_bancaria} · marca {empresa.prefixo_marca}")
        if remoto:
            st.markdown(f"**{html.escape(identidade.nome)}**  \n{html.escape(identidade.email or '')}",
                        unsafe_allow_html=True)
            st.caption("Seu nome e e-mail identificam suas ações no histórico e nos relatórios.")
            usuario = identidade.para_auditoria
        else:
            nome_digitado = st.text_input(
                "Responsável pela revisão", "operador",
                help="Este nome aparece na trilha de auditoria e nos relatórios.",
            )
            usuario = (acesso.Identidade(nome_digitado, None, False).para_auditoria
                       if config_acesso.remoto else nome_digitado)
        leiaute = st.radio("Arquivo de exportação", ["Fortes", "CSV genérico"], horizontal=True)
        if usar_ia:
            st.warning("Sugestão por IA ligada: históricos serão enviados ao provedor de IA.")
        if pasta_backup.strip():
            from motor_contabil.backup import horas_desde_ultima

            horas = horas_desde_ultima(pasta_backup.strip())
            if horas is None:
                st.error("Nenhuma cópia de segurança encontrada na pasta de backup.")
            elif horas > 26:
                st.error(f"Última cópia de segurança há {horas:.0f} horas. Confira o agendamento.")
            else:
                st.caption(f"Cópia de segurança em dia (há {horas:.1f} h).")


def registrar_download(caminho: str, responsavel: str, lote_id: int) -> None:
    # Callbacks do Streamlit rodam em outra thread; o SQLite exige conexão própria.
    banco = BancoDeDados(caminho)
    try:
        banco.registrar_evento(responsavel, "arquivo_baixado", f"lote {lote_id}", lote_id=lote_id)
        banco.conexao.commit()
    finally:
        banco.fechar()


def registrar_relatorio(caminho: str, responsavel: str, detalhe: str) -> None:
    banco = BancoDeDados(caminho)
    try:
        banco.registrar_evento(responsavel, "relatorio_baixado", detalhe)
        banco.conexao.commit()
    finally:
        banco.fechar()


def oferecer_relatorio(chave: str, rotulo: str) -> None:
    """Mostra o botão de download de um relatório já gerado e guardado na sessão."""
    if pronto := st.session_state.get(chave):
        nome, conteudo = pronto
        st.download_button(
            rotulo, conteudo, file_name=nome, mime="application/pdf", key=f"baixar-{chave}",
            on_click=registrar_relatorio, args=(caminho_db, usuario, nome),
        )


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
    st.html(
        '<nav class="cf-navegacao" aria-label="Etapas da conciliação">'
        '<a href="#importar-extrato">1. Importar extrato</a>'
        '<a href="#revisar-lancamentos">2. Revisar lançamentos</a>'
        '<a href="#exportar-fortes">3. Exportar</a>'
        '<a href="#conferir-banco">4. Conferir o banco</a>'
        '<a href="#relatorio-processamento">5. Relatório</a>'
        '</nav>'
    )
    painel = st.empty()
    st.html('<div id="como-comecar" class="cf-ancora"></div>')
    with st.expander("Primeira vez? Veja como começar"):
        st.markdown(
            "1. Escolha a **Empresa** na barra lateral.\n"
            "2. Em **Importar extrato**, escolha o arquivo e clique em **Processar extrato**.\n"
            "3. Em **Revisar lançamentos**, decida quais contas usar nos movimentos pendentes ou bloqueados.\n"
            "4. Em **Exportar**, gere e baixe o lote para importar no Fortes.\n"
            "5. Depois da importação no Fortes, use **Conferir o banco** para comparar os arquivos. "
            "Use **Relatório** para baixar um resumo do período."
        )
        if treinamento:
            st.caption("A empresa de treinamento já tem lançamentos. Você pode começar pela revisão.")

    # ------------------------------------------------------------------ importar
    st.subheader(f"1. Importar extrato · {empresa.nome}", anchor="importar-extrato")
    st.write("Escolha o arquivo do banco e clique em **Processar extrato**. Depois, confira o período e os totais.")
    with st.expander("Quais arquivos posso usar?"):
        st.markdown(
            "- **OFX ou OFC** do internet banking. Prefira esse formato quando estiver disponível.\n"
            "- **CSV ou TXT** com cabeçalho e colunas de data, histórico e valor.\n"
            "- **XLSX** com uma única planilha de movimentação.\n"
            "- **PDF do Itaú** no modelo Entradas e Saídas.\n\n"
            f"Limite de {TAMANHO_MAXIMO // (1024 * 1024)} MB por arquivo."
        )
    if treinamento:
        exemplo = interface.parent / "exemplos" / "extrato_exemplo.csv"
        st.download_button(
            "Baixar extrato fictício para praticar",
            exemplo.read_bytes(),
            file_name="extrato_treinamento.csv",
            mime="text/csv",
            on_click="ignore",
        )
    chave_relatorio = f"relatorio_importacao_{empresa.identificador}"
    arquivo = st.file_uploader(
        "Extrato OFX, CSV, planilha XLSX ou extrato Itaú em PDF",
        type=[e.lstrip(".") for e in EXTENSOES_ACEITAS],
    )
    if arquivo is None:
        st.caption("Selecione um arquivo acima para habilitar o botão.")
    if arquivo:
        conteudo = arquivo.getvalue()
        if outras := empresas.empresas_com_o_arquivo(pasta_dados, conteudo, empresa.identificador):
            st.warning(
                f"Este mesmo arquivo já foi recebido na empresa {', '.join(outras)}. "
                f"Confira se ele é mesmo de {empresa.nome} antes de processar."
            )
    if st.button("Processar extrato", type="primary", disabled=arquivo is None) and arquivo is not None:
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
            st.markdown("[Ir para a revisão](#revisar-lancamentos)")
        else:
            st.error(f"{relatorio.titulo}. {relatorio.detalhe}")
            st.info(f"O que fazer: {relatorio.o_que_fazer}")

    # ------------------------------------------------------------------ revisar
    st.subheader("2. Revisar lançamentos", anchor="revisar-lancamentos")
    todos = motor.listar()
    contagem = {s: sum(1 for i in todos if i["status"] == s.value) for s in Status}
    painel.html(painel_inicial(empresa.nome, todos, contagem))
    st.write(
        "Comece por **Pendentes** e **Bloqueados**. Confira o histórico, a data e o valor. "
        "Em **Contrapartida**, escolha a conta que explica o movimento e clique em **Aprovar**."
    )
    with st.expander("O que significa cada situação?"):
        st.markdown(
            "- **Pendente** · Precisa de uma decisão. Confira o motivo no lançamento.\n"
            "- **Bloqueado** · Leia o motivo e corrija o problema indicado antes de tentar aprovar.\n"
            "- **Liberado** · Pode entrar no próximo arquivo para o Fortes.\n"
            "- **Exportado** · Já está em um lote. Use **Baixar lote** para recuperar o arquivo.\n"
            "- **Descartado** · Foi retirado da revisão. O motivo fica registrado."
        )
    m = st.columns(4)
    m[0].metric("Pendentes", contagem[Status.PENDENTE], border=True,
                help="Precisam de uma decisão: escolher a conta, aprovar ou descartar.")
    m[1].metric("Bloqueados", contagem[Status.BLOQUEADO], border=True,
                help="Conta inexistente ou sintética: corrija a conta para liberar.")
    m[2].metric("Liberados", contagem[Status.LIBERADO], border=True,
                help="Prontos para o arquivo do Fortes (seção 3).")
    m[3].metric("Exportados", contagem[Status.EXPORTADO], border=True,
                help="Já saíram num arquivo de importação e não podem mais ser alterados.")

    nomes_filtro = {
        "pendente": "Pendentes", "bloqueado": "Bloqueados", "liberado": "Liberados",
        "exportado": "Exportados", "descartado": "Descartados",
    }
    escopo_revisao = sha256(str(Path(caminho_db).resolve()).encode("utf-8")).hexdigest()
    chave_pagina = f"pagina-revisao-{escopo_revisao}"
    filtro = st.segmented_control(
        "Mostrar", list(nomes_filtro), default="pendente", key="filtro-status",
        format_func=lambda k: f"{nomes_filtro[k]} ({contagem[Status(k)]})",
        on_change=reiniciar_pagina, args=(chave_pagina,),
    ) or "pendente"
    busca_coluna, mes_coluna = st.columns([3, 2])
    busca = busca_coluna.text_input(
        "Buscar lançamentos", placeholder="Histórico, código ou conta",
        key=f"busca-revisao-{escopo_revisao}", on_change=reiniciar_pagina, args=(chave_pagina,),
    )
    meses = sorted({i["data"][:7] for i in todos}, reverse=True)
    competencia = mes_coluna.selectbox(
        "Competência", [None, *meses],
        format_func=lambda mes: f"{mes[5:]}/{mes[:4]}" if mes else "Todos os meses",
        help="Mostra os lançamentos do mês escolhido na revisão.",
        key=f"mes-revisao-{escopo_revisao}", on_change=reiniciar_pagina, args=(chave_pagina,),
    )
    consulta = normalizar(busca)
    itens = [
        i for i in todos
        if i["status"] == filtro
        and (competencia is None or i["data"].startswith(competencia))
        and (not consulta or corresponde_busca(i, consulta))
    ]
    quantidade = len(itens)
    if quantidade > ITENS_POR_PAGINA:
        paginas = (quantidade + ITENS_POR_PAGINA - 1) // ITENS_POR_PAGINA
        if st.session_state.get(chave_pagina, 1) > paginas:
            st.session_state[chave_pagina] = paginas
        pagina = st.selectbox("Página de lançamentos", range(1, paginas + 1), key=chave_pagina)
        inicio = (pagina - 1) * ITENS_POR_PAGINA
        itens = itens[inicio:inicio + ITENS_POR_PAGINA]
        st.caption(f"Exibindo {inicio + 1} a {inicio + len(itens)} de {quantidade} lançamentos.")
    elif itens:
        st.caption(f"{quantidade} lançamento{'s' if quantidade != 1 else ''} na seleção.")
    analiticas = motor.plano.analiticas()
    contas = [c.codigo for c in analiticas]
    rotulos = {c.codigo: f"{c.codigo} - {c.descricao}" for c in analiticas}

    def nome_conta(codigo: str | None) -> str:
        conta = motor.plano.get(codigo) if codigo else None
        nome = f" {html.escape(conta.descricao)}" if conta else ""
        return f"<code>{html.escape(codigo or '')}</code>{nome}"

    if not itens:
        vazio = {
            "pendente": (
                "Nenhum lançamento pendente. Confira os bloqueados se houver."
                if todos else "Importe um extrato para ver os lançamentos aqui."
            ),
            "bloqueado": "Nenhum lançamento bloqueado.",
        }
        if consulta or competencia:
            st.info("Nenhum lançamento com esses filtros. Altere a busca ou a competência.")
        else:
            st.info(vazio.get(filtro, f"Nenhum lançamento em \"{nomes_filtro[filtro]}\"."))
    for item in itens:
        with st.container(border=True, key=f"cf-lancamento-{item['chave']}"):
            estado = Status(item["status"])
            simbolo, rotulo_estado = ESTADOS_VISUAIS[estado]
            st.html(
                f'<span class="cf-estado" data-estado="{estado.value}">'
                f'<span aria-hidden="true">{simbolo}</span>{rotulo_estado}</span>'
            )
            topo, valor = st.columns([5, 1.4])
            topo.markdown(
                f"**{texto_literal(item['historico_banco'])}**  \n"
                f"<span class='cf-meta'>{data_br(item['data'])} · {html.escape(item['origem'])}, "
                f"linha {item['linha']} · <code>{html.escape(item['chave'][:12])}</code></span>",
                unsafe_allow_html=True,
            )
            sentido = "saida" if Decimal(item["valor"]) < 0 else "entrada"
            valor.html(
                f'<div class="cf-valor" data-sentido="{sentido}">{brl(item["valor"])}</div>'
            )
            for motivo in filter(None, item["motivos"].split(" | ")):
                st.html(f'<p class="cf-motivo">{html.escape(motivo)}</p>')
            if item["conta_debito"] and item["conta_credito"]:
                st.html(
                    f"<div class='cf-partida'>Débito {nome_conta(item['conta_debito'])} · "
                    f"Crédito {nome_conta(item['conta_credito'])}</div>"
                )
            if filtro in ("pendente", "bloqueado", "liberado"):
                atual = item["conta_contrapartida"]
                x, y, z = st.columns([3.6, 1.05, 1.25], vertical_alignment="bottom")
                escolhida = x.selectbox(
                    "Contrapartida", contas,
                    index=contas.index(atual) if atual in contas else None,
                    format_func=lambda k: rotulos[k], key=f"conta-{item['chave']}",
                    placeholder="Escolha a conta",
                    help="Conta do plano que explica o movimento, como tarifa bancária ou fornecedor.",
                )
                if y.button("Aprovar", key=f"ok-{item['chave']}", disabled=escolhida is None,
                            type="primary" if filtro != "liberado" else "secondary",
                            use_container_width=True):
                    try:
                        motor.aprovar(item["chave"], escolhida if escolhida != atual else None)
                        st.rerun()
                    except (ValueError, KeyError) as erro:
                        st.error(f"Não foi possível aprovar: {erro}")
                with z.popover("Descartar", use_container_width=True):
                    st.caption("Use só para duplicidade ou movimento que não deve ser lançado. "
                               "Fica registrado na trilha de auditoria.")
                    motivo = st.text_input("Motivo do descarte", key=f"mot-{item['chave']}")
                    if st.button("Confirmar descarte", key=f"x-{item['chave']}",
                                 disabled=not motivo.strip()):
                        try:
                            motor.descartar(item["chave"], motivo)
                            st.rerun()
                        except (ValueError, KeyError) as erro:
                            st.error(f"Não foi possível descartar: {erro}")

    # ------------------------------------------------------------------ exportar
    st.subheader("3. Gerar arquivo para o Fortes", anchor="exportar-fortes")
    st.write("Gere um lote e baixe o arquivo. Você importa esse arquivo dentro do Fortes Contábil.")
    st.caption("O lote reúne todos os lançamentos liberados da empresa, inclusive os de outros meses.")
    if not contagem[Status.LIBERADO]:
        st.caption("Para gerar um lote novo, importe um extrato ou revise os lançamentos em aberto.")
    if leiaute == "Fortes":
        with st.expander("Como importar o arquivo no Fortes?"):
            st.write(
                "No Fortes Contábil, abra a importação de lançamentos e selecione o arquivo baixado. "
                "Marque **Desconsiderar Identificador** e **Utilizar Código Reduzido**."
            )
        st.warning("Valide a importação em uma empresa de teste do Fortes.")
    else:
        st.warning("CSV genérico: leiaute provisório, não corresponde a nenhum sistema contábil. "
                   "Para o Fortes, escolha \"Fortes\" na barra lateral.")
    if st.button(f"Gerar arquivo de importação ({contagem[Status.LIBERADO]} liberados)",
                 disabled=contagem[Status.LIBERADO] == 0, type="primary"):
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
        st.caption("Para recuperar um lote antigo, use o botão Baixar lote correspondente.")
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
    st.subheader("4. Conferir o banco: extrato x contabilidade", anchor="conferir-banco")
    st.write(
        "Selecione o extrato completo do Itaú e os arquivos do mesmo período já importados no Fortes. "
        "Clique em **Conferir** para comparar os saldos e os movimentos."
    )
    with st.expander("Quais arquivos preciso separar?"):
        st.markdown(
            "- **Extrato completo do Itaú em PDF**, com entradas, saídas e saldos.\n"
            "- **Arquivos CSV ou TXT já importados no Fortes** para a conta bancária da empresa."
        )
    c1, c2 = st.columns(2)
    chave_conferencia = f"resultado-conferencia-{escopo_revisao}"
    chave_pdf_conferencia = f"pdf-conferencia-{escopo_revisao}"
    extrato_pdf = c1.file_uploader(
        "Extrato Itaú em PDF", type=["pdf"], key=f"conf-extrato-{escopo_revisao}",
    )
    importados = c2.file_uploader(
        "Arquivos já importados no Fortes", type=["csv", "txt"], accept_multiple_files=True,
        key=f"conf-importados-{escopo_revisao}",
    )
    reduzido_banco = empresa.conta_bancaria
    if not extrato_pdf or not importados:
        st.caption("Selecione os arquivos nos dois campos para habilitar a conferência.")
    elif not reduzido_banco:
        st.warning("Informe a conta bancária no cadastro da empresa para fazer a conferência.")
    pode_conferir = bool(extrato_pdf and importados and reduzido_banco)
    if st.button("Conferir", type="primary", disabled=not pode_conferir) and pode_conferir:
        from motor_contabil.leitores import ler_itau_pdf_completo

        st.session_state.pop(chave_conferencia, None)
        st.session_state.pop(chave_pdf_conferencia, None)
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
            resultado = ConferenciaExibida(
                extrato_pdf.name, tuple(a.name for a in importados),
                len(extrato.transacoes), extrato.dias_conferidos, linhas, total,
            )
            pdf_conferencia = relatorios.relatorio_conciliacao(
                empresa.nome, empresa.cnpj, reduzido_banco.strip(), linhas, total, usuario,
                resultado.extrato, list(resultado.importados), resultado.dias_conferidos,
                resultado.movimentos,
            )
            st.session_state[chave_conferencia] = resultado
            st.session_state[chave_pdf_conferencia] = (
                f"conferencia_banco_{empresa.identificador}_{date.today():%Y%m%d}.pdf", pdf_conferencia,
            )
        except Exception as erro:
            st.error(
                f"Não foi possível conferir. Verifique se o PDF é o extrato completo do Itaú "
                f"e se os arquivos correspondem à conta da empresa. Detalhe: {erro}"
            )
    if resultado := st.session_state.get(chave_conferencia):
        mostrar_conferencia(resultado)
    oferecer_relatorio(chave_pdf_conferencia,
                       "Baixar relatório da conferência (PDF, para revisão e auditoria)")

    # ------------------------------------------------------------------ relatórios
    st.subheader("5. Relatório de processamento e revisão", anchor="relatorio-processamento")
    st.write(
        "Escolha o período e clique em **Gerar relatório**. "
        "Baixe o PDF para conferir o que foi processado e o que ainda precisa de revisão."
    )
    with st.expander("O que vou encontrar no PDF?"):
        st.write(
            "O relatório mostra os lançamentos classificados por regra, as revisões, "
            "as pendências, os descartes e os lotes gerados. Inclui um quadro para o contador assinar."
        )
    maximo = motor.banco.conexao.execute("SELECT MAX(data) FROM transacoes").fetchone()[0]
    if not maximo:
        st.info("Importe um extrato para gerar o relatório.")
    else:
        ultimo = date.fromisoformat(maximo)
        c1, c2 = st.columns(2)
        inicio = c1.date_input("De", ultimo.replace(day=1), format="DD/MM/YYYY", key="rel-inicio")
        fim_do_mes = ultimo.replace(day=calendar.monthrange(ultimo.year, ultimo.month)[1])
        fim = c2.date_input("Até", fim_do_mes, format="DD/MM/YYYY", key="rel-fim")
        if inicio > fim:
            st.warning("A data inicial deve ser igual ou anterior à data final. Ajuste os campos De e Até.")
        if st.button("Gerar relatório", disabled=inicio > fim, type="primary"):
            try:
                dados_rel = relatorios.coletar_processamento(
                    motor.banco.conexao, empresa.nome, empresa.cnpj, empresa.conta_bancaria,
                    inicio, fim, motor.plano)
                st.session_state[f"rel_proc_{empresa.identificador}"] = (
                    f"processamento_{empresa.identificador}_{inicio:%Y%m%d}_{fim:%Y%m%d}.pdf",
                    relatorios.relatorio_processamento(dados_rel, usuario),
                )
                ind = relatorios.calcular_indicadores(dados_rel)
                st.success(
                    f"Relatório gerado: {ind.total} transações, {ind.automaticos} classificadas por regra "
                    f"sem intervenção ({ind.taxa_automatica:.0%}), {ind.em_aberto} em aberto."
                )
            except Exception as erro:
                st.error(f"Não foi possível gerar o relatório: {erro}")
        oferecer_relatorio(f"rel_proc_{empresa.identificador}", "Baixar relatório de processamento (PDF)")

finally:
    motor.banco.fechar()
