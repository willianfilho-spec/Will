"""Rotas da equipe contábil: /e/{slug}/... (operador, revisor, aprovador)."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from domain import conciliacao_razao as cr
from domain import documentos as doc
from domain import lancamentos as lanc
from domain import operacoes as o
from domain.money import para_centavos
from parsers import tabular_parser
from parsers.comum import ErroEstrutural
from storage import audit
from storage.database import parametro
from storage.usuarios import AcessoNegado, pode
from web.base import (EQUIPE, Atual, atual_dep, falhou, ler_form, nome_seguro, pagina, papel, tentar, voltar)

router = APIRouter(prefix="/e/{slug}")


def ctx_equipe(slug: str, request: Request, atual: Atual = Depends(atual_dep)):
    try:
        ctx = o.Contexto.abrir(atual.central, atual.usuario, slug, request.app.state.data_dir)
    except AcessoNegado:
        raise HTTPException(404, "Empresa não encontrada") from None
    try:
        if papel(atual, ctx.empresa["id"]) not in EQUIPE:
            raise HTTPException(403, "Esta área é da equipe contábil")
        yield ctx
    finally:
        ctx.con.close()


def _u(ctx, caminho: str = "") -> str:
    return f"/e/{ctx.empresa['slug']}{caminho}"


def _periodos(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT p FROM (SELECT DISTINCT substr(data, 1, 7) p FROM movimentos UNION SELECT DISTINCT substr(data, 1, 7) "
        "FROM lancamentos) ORDER BY p DESC")]


def _sel(ctx, request: Request) -> tuple[str | None, str | None, list[str]]:
    ps = _periodos(ctx.con)
    p = request.query_params.get("periodo") or (ps[0] if ps else None)
    c = request.query_params.get("conta") or parametro(ctx.con, "conta_banco_padrao")
    return (p if p in ps else (ps[0] if ps else None)), c, ps


def _pode(atual: Atual, ctx, acao: str) -> bool:
    return pode(atual.central, atual.usuario["id"], ctx.empresa["id"], acao)


def _mov_url(ctx, i: int) -> str:
    return _u(ctx, f"/revisao/mov/{int(i)}")


# ================================================================== resumo

@router.get("", response_class=HTMLResponse)
def resumo(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    con = ctx.con
    n = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    return pagina(request, atual, "e_resumo.html", emp=ctx.empresa, papel_emp=papel(atual, ctx.empresa["id"]),
                  por_status=con.execute("SELECT status, COUNT(*) n FROM movimentos GROUP BY status").fetchall(),
                  lanc_aguardando=n("SELECT COUNT(*) FROM lancamentos WHERE status = 'aguardando_confirmacao'"),
                  docs_recebidos=n("SELECT COUNT(*) FROM documentos WHERE status = 'recebido'"),
                  solic_abertas=n("SELECT COUNT(*) FROM solicitacoes WHERE status = 'aberta'"),
                  solic_respondidas=n("SELECT COUNT(*) FROM solicitacoes WHERE status = 'respondida'"),
                  dup_pendentes=n("SELECT COUNT(*) FROM movimentos WHERE decisao_duplicidade = 'pendente'"),
                  segunda=n("SELECT COUNT(*) FROM movimentos WHERE status = 'classificado' AND exige_segunda_confirmacao = 1 "
                            "AND segunda_confirmacao_por IS NULL"),
                  fila=n("SELECT COUNT(*) FROM movimentos WHERE status IN ('pendente', 'proposto')"))


@router.post("/integridade")
async def integridade(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    await ler_form(request, atual)

    def fn():
        prob = o.verificar_integridade(ctx) + audit.verificar_cadeia(atual.central, "audit_acesso")
        if prob:
            raise ErroEstrutural(prob)
        return "Integridade verificada: arquivos, lotes, documentos e cadeia de auditoria sem problemas."
    return tentar(atual, _u(ctx), fn, lambda r: r)


# ================================================================== cargas e documentos

@router.get("/cargas", response_class=HTMLResponse)
def cargas(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    return pagina(request, atual, "e_cargas.html", emp=ctx.empresa, docs=doc.listar(ctx), categorias=doc.CATEGORIAS,
                  arquivos=ctx.con.execute("SELECT * FROM arquivos ORDER BY id DESC").fetchall())


@router.post("/cargas/enviar")
async def cargas_enviar(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    arq = f.get("arquivo")

    async def fn():
        if arq is None or not getattr(arq, "filename", None):
            raise ErroEstrutural(["escolha um arquivo"])
        return doc.enviar(ctx, arq.filename, await arq.read(), str(f.get("categoria", "outro")), str(f.get("descricao", "")))
    try:
        i = await fn()
    except Exception as exc:  # noqa: BLE001
        return falhou(atual, _u(ctx, "/cargas"), exc)
    return voltar(atual, _u(ctx, f"/documentos/{i}"), ok="Arquivo recebido. Confira e processe.")


@router.get("/documentos/{doc_id}", response_class=HTMLResponse)
def documento(doc_id: int, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    try:
        d, bruto = doc.obter(ctx, doc_id)
    except o.OperacaoInvalida:
        raise HTTPException(404, "Documento não encontrado") from None
    previa, colunas, sug = [], [], {}
    if d["categoria"] in ("extrato", "planilha") and not d["nome_original"].lower().endswith(".ofx"):
        try:
            colunas, linhas = tabular_parser.ler_tabela(bruto, d["nome_original"])
            previa, sug = linhas[:6], tabular_parser.sugerir_mapeamento(colunas)
        except ErroEstrutural as exc:
            previa = [{"erro": p} for p in exc.problemas[:5]]
    return pagina(request, atual, "e_documento.html", emp=ctx.empresa, d=d, previa=previa, colunas=colunas, sug=sug,
                  ofx=d["nome_original"].lower().endswith(".ofx"), contas=o.contas_analiticas(ctx.con),
                  conta_padrao=parametro(ctx.con, "conta_banco_padrao"), tipos=("", *__import__("config").TIPOS_LANCAMENTO))


@router.get("/documentos/{doc_id}/baixar")
def documento_baixar(doc_id: int, ctx=Depends(ctx_equipe)):
    try:
        d, bruto = doc.obter(ctx, doc_id)
    except o.OperacaoInvalida:
        raise HTTPException(404, "Documento não encontrado") from None
    return Response(bruto, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{nome_seguro(d["nome_original"])}"'})


def _mapa(f) -> tabular_parser.Mapeamento:
    g = lambda k: (str(f.get(k, "")).strip() or None)  # noqa: E731
    return tabular_parser.Mapeamento(data=g("col_data") or "", historico=g("col_historico") or "", valor=g("col_valor"),
                                     entrada=g("col_entrada"), saida=g("col_saida"), documento=g("col_documento"),
                                     inverter_sinal=f.get("inverter") == "1")


@router.post("/documentos/{doc_id}/processar")
async def documento_processar(doc_id: int, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    url = _u(ctx, f"/documentos/{doc_id}")

    def fn():
        d, bruto = doc.obter(ctx, doc_id)
        if d["status"] != "recebido":
            raise o.OperacaoInvalida(f"documento já {d['status']}")
        cat, ofx = d["categoria"], d["nome_original"].lower().endswith(".ofx")
        if cat == "extrato":
            r = doc.processar_extrato(ctx, doc_id, str(f.get("conta_banco", "")), None if ofx else _mapa(f))
            return (f"{r['movimentos']} movimentos carregados: {r['propostos']} com proposta de regra, "
                    f"{r['alertas_duplicidade']} alerta(s) de duplicidade, {r['segunda_revisao']} com segunda revisão.")
        if cat == "planilha":
            r = o.carregar_planilha_despesas(ctx, d["nome_original"], bruto, _mapa(f))
            doc.marcar_processado(ctx, doc_id, f"{r['itens']} despesas")
            return f"{r['itens']} despesas carregadas como pista de identificação."
        if cat == "lancamentos":
            r = lanc.importar_leiaute_fortes(ctx, d["nome_original"], bruto, str(f.get("tipo", "")) or None, doc_id)
            doc.marcar_processado(ctx, doc_id, f"{r['criados']} lançamentos")
            return f"{r['criados']} lançamentos importados; aguardam a confirmação de outra pessoa."
        if cat == "razao":
            r = o.carregar_razao(ctx, d["nome_original"], bruto, "fortes_importacao")
            doc.marcar_processado(ctx, doc_id, f"{r['partidas']} partidas")
            return f"Razão carregado: {r['partidas']} partidas (formato do leiaute de importação)."
        raise o.OperacaoInvalida("este tipo de documento é só de consulta; não há o que processar")
    return tentar(atual, url, fn, lambda r: r)


@router.post("/documentos/{doc_id}/recusar")
async def documento_recusar(doc_id: int, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    return tentar(atual, _u(ctx, "/cargas"), lambda: doc.recusar(ctx, doc_id, str(f.get("motivo", ""))), "Documento recusado.")


# ================================================================== revisão

@router.get("/revisao", response_class=HTMLResponse)
def revisao(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    aba = request.query_params.get("aba", "fila")
    q = lambda cond: ctx.con.execute(f"SELECT * FROM movimentos WHERE {cond} ORDER BY data, id").fetchall()  # noqa: E731
    contas = {r["reduzido"]: f"{r['reduzido']} · {r['descricao']}" for r in o.contas_analiticas(ctx.con)}
    dados = {"fila": q("status IN ('pendente', 'proposto')"),
             "segunda": q("status = 'classificado' AND exige_segunda_confirmacao = 1 AND segunda_confirmacao_por IS NULL"),
             "duplicidades": q("decisao_duplicidade = 'pendente'"), "espera": q("status = 'em_espera'"),
             "todos": q("1 = 1")}
    return pagina(request, atual, "e_revisao.html", emp=ctx.empresa, aba=aba if aba in dados else "fila", dados=dados,
                  contas=contas, eu=ctx.nome, pode_segunda=_pode(atual, ctx, "segunda_confirmacao"),
                  pode_dup=_pode(atual, ctx, "decidir_duplicidade"), pode_classificar=_pode(atual, ctx, "classificar"))


@router.post("/revisao/aceitar")
async def revisao_aceitar(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)

    def fn():
        ids = [int(i) for i in f.getlist("ids")]
        if not ids:
            raise o.OperacaoInvalida("marque ao menos uma proposta")
        for i in ids:
            m = ctx.con.execute("SELECT * FROM movimentos WHERE id = ? AND status = 'proposto'", (i,)).fetchone()
            if m is None:
                raise o.OperacaoInvalida(f"movimento {i} não está proposto")
            contra = m["conta_debito"] if m["valor_centavos"] < 0 else m["conta_credito"]
            o.classificar(ctx, i, contra, m["historico_contabil"], m["natureza"], "regra")
        return len(ids)
    return tentar(atual, _u(ctx, "/revisao"), fn, lambda n: f"{n} proposta(s) aceita(s).")


@router.get("/revisao/mov/{mov_id}", response_class=HTMLResponse)
def revisao_mov(mov_id: int, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    m = ctx.con.execute("SELECT * FROM movimentos WHERE id = ?", (mov_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Movimento não encontrado")
    atual_contra = None
    if m["conta_debito"]:
        atual_contra = m["conta_debito"] if m["valor_centavos"] < 0 else m["conta_credito"]
    return pagina(request, atual, "e_mov.html", emp=ctx.empresa, m=m, pistas=o.pistas_planilha(ctx.con, m),
                  contas=o.contas_analiticas(ctx.con), contra=atual_contra, naturezas=o.NATUREZAS,
                  solic=ctx.con.execute("SELECT * FROM solicitacoes WHERE movimento_id = ?", (mov_id,)).fetchall())


@router.post("/revisao/mov/{mov_id}/classificar")
async def mov_classificar(mov_id: int, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)

    def fn():
        m = ctx.con.execute("SELECT * FROM movimentos WHERE id = ?", (mov_id,)).fetchone()
        conta = str(f.get("conta", ""))
        ant = (m["conta_debito"] if m["valor_centavos"] < 0 else m["conta_credito"]) if m and m["conta_debito"] else None
        origem = "regra" if m and m["status"] == "proposto" and conta == ant else "manual"
        return o.classificar(ctx, mov_id, conta, str(f.get("historico", "")) or None, str(f.get("natureza", "normal")), origem)
    return tentar(atual, _u(ctx, "/revisao"), fn,
                  lambda motivos: "Classificado." + (f" Exige segunda confirmação: {'; '.join(motivos)}." if motivos else ""))


@router.post("/revisao/mov/{mov_id}/{acao}")
async def mov_acao(mov_id: int, acao: str, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    url, txt = _u(ctx, "/revisao"), str(f.get("texto", ""))
    acoes = {
        "espera": (lambda: o.colocar_em_espera(ctx, mov_id, txt), "Movimento em espera."),
        "retomar": (lambda: o.retomar(ctx, mov_id), "Movimento retomado."),
        "segunda": (lambda: o.segunda_confirmacao(ctx, mov_id), "Segunda confirmação registrada."),
        "devolver": (lambda: o.devolver(ctx, mov_id, txt), "Item devolvido à fila."),
        "manter": (lambda: o.decidir_duplicidade(ctx, mov_id, "manter", txt), "Mantido; vai exigir segunda confirmação."),
        "descartar": (lambda: o.decidir_duplicidade(ctx, mov_id, "descartar", txt), "Descartado como duplicado."),
        "solicitar": (lambda: doc.criar_solicitacao(ctx, txt, mov_id), "Solicitação enviada ao cliente."),
    }
    if acao not in acoes:
        raise HTTPException(404)
    fn, ok = acoes[acao]
    return tentar(atual, _mov_url(ctx, mov_id) if acao == "solicitar" else url, fn, ok)


# ================================================================== lançamentos manuais

@router.get("/lancamentos", response_class=HTMLResponse)
def lancamentos(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    import config
    return pagina(request, atual, "e_lancamentos.html", emp=ctx.empresa, itens=lanc.listar(ctx.con),
                  contas=o.contas_analiticas(ctx.con), tipos=config.TIPOS_LANCAMENTO, eu=ctx.nome,
                  docs=ctx.con.execute("SELECT id, nome_original FROM documentos ORDER BY id DESC LIMIT 100").fetchall(),
                  pode_confirmar=_pode(atual, ctx, "segunda_confirmacao"))


@router.post("/lancamentos/criar")
async def lancamentos_criar(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)

    def fn():
        d = str(f.get("documento_id", "")).strip()
        return lanc.criar(ctx, str(f.get("tipo", "")), str(f.get("data", "")), str(f.get("debito", "")),
                          str(f.get("credito", "")), para_centavos(str(f.get("valor", ""))), str(f.get("historico", "")),
                          int(d) if d.isdigit() else None, None, str(f.get("observacao", "")) or None,
                          str(f.get("justificativa", "")) or None)
    return tentar(atual, _u(ctx, "/lancamentos"), fn, "Lançamento criado; aguarda a confirmação de outra pessoa.")


@router.post("/lancamentos/importar")
async def lancamentos_importar(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    arq = f.get("arquivo")

    def fn(bruto):
        if arq is None or not getattr(arq, "filename", None):
            raise ErroEstrutural(["escolha um arquivo"])
        doc.validar_upload(arq.filename, bruto)
        return lanc.importar_leiaute_fortes(ctx, arq.filename, bruto, str(f.get("tipo", "")) or None)
    bruto = await arq.read() if arq is not None and getattr(arq, "filename", None) else b""
    return tentar(atual, _u(ctx, "/lancamentos"), lambda: fn(bruto),
                  lambda r: f"{r['criados']} lançamentos importados; cada um aguarda confirmação de outra pessoa.")


@router.post("/lancamentos/{lid}/{acao}")
async def lancamentos_acao(lid: int, acao: str, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    if acao == "confirmar":
        return tentar(atual, _u(ctx, "/lancamentos"), lambda: lanc.confirmar(ctx, lid), "Lançamento confirmado.")
    if acao == "descartar":
        return tentar(atual, _u(ctx, "/lancamentos"), lambda: lanc.descartar(ctx, lid, str(f.get("motivo", ""))),
                      "Lançamento descartado.")
    raise HTTPException(404)


# ================================================================== conferência

def _dados_conferencia(ctx, periodo, conta):
    if not periodo or not conta:
        return {}
    return {"saldos": ctx.con.execute("SELECT * FROM saldos_extrato WHERE periodo = ? AND conta_banco = ?", (periodo, conta)).fetchone(),
            "conc": o.conciliacao(ctx.con, periodo, conta)}


@router.get("/conferencia", response_class=HTMLResponse)
def conferencia(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    periodo, conta, ps = _sel(ctx, request)
    return pagina(request, atual, "e_conferencia.html", emp=ctx.empresa, periodo=periodo, conta=conta, periodos=ps,
                  contas=o.contas_analiticas(ctx.con), comparacao=None, eu=ctx.nome,
                  pode_revisar=_pode(atual, ctx, "revisar_diferenca"), **_dados_conferencia(ctx, periodo, conta))


@router.post("/conferencia/{acao}")
async def conferencia_acao(acao: str, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    periodo, conta = str(f.get("periodo", "")), str(f.get("conta", ""))
    url = _u(ctx, f"/conferencia?periodo={periodo}&conta={conta}")
    if acao == "comparar":
        try:
            res = cr.comparar(ctx, periodo, conta)
        except Exception as exc:  # noqa: BLE001
            return falhou(atual, url, exc)
        ps = _periodos(ctx.con)
        return pagina(request, atual, "e_conferencia.html", emp=ctx.empresa, periodo=periodo, conta=conta, periodos=ps,
                      contas=o.contas_analiticas(ctx.con), comparacao=res, eu=ctx.nome,
                      pode_revisar=_pode(atual, ctx, "revisar_diferenca"), **_dados_conferencia(ctx, periodo, conta))
    fns = {
        "saldos": (lambda: (o.informar_saldos(ctx, periodo, conta, para_centavos(str(f.get("inicial", ""))),
                                              para_centavos(str(f.get("final", "")))), o.conferir(ctx, periodo, conta)),
                   "Saldos gravados e conferência atualizada."),
        "conferir": (lambda: o.conferir(ctx, periodo, conta), "Conferência atualizada."),
        "justificar": (lambda: o.justificar_diferenca(ctx, periodo, conta, str(f.get("texto", ""))),
                       "Justificativa registrada; falta a segunda revisão."),
        "revisar": (lambda: o.revisar_diferenca(ctx, periodo, conta), "Diferença revisada (a conciliação fica 'justificada')."),
    }
    if acao not in fns:
        raise HTTPException(404)
    fn, ok = fns[acao]
    return tentar(atual, url, fn, ok)


# ================================================================== exportação

@router.get("/exportacao", response_class=HTMLResponse)
def exportacao(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    periodo, conta, ps = _sel(ctx, request)
    movs, problemas, lotes = [], [], []
    if periodo and conta:
        movs, problemas = o.pre_validar_lote(ctx, periodo, conta)
        lotes = ctx.con.execute("SELECT * FROM lotes WHERE periodo = ? AND conta_banco = ? ORDER BY id DESC", (periodo, conta)).fetchall()
    lim = o.limite_historico(ctx.con)
    from exporters import fortes_exporter as fe
    cortes = [m["id"] for m in movs if fe.montar_historico(m.get("historico_contabil") or m["historico"],
                                                           m.get("_marca") or fe.marca(ctx.prefixo, m["data"], m["id"]), lim)[1]]
    return pagina(request, atual, "e_exportacao.html", emp=ctx.empresa, periodo=periodo, conta=conta, periodos=ps,
                  total=sum(abs(m["valor_centavos"]) for m in movs),
                  contas=o.contas_analiticas(ctx.con), movs=movs, problemas=problemas, lotes=lotes, limite=lim, cortes=cortes,
                  conf={l["id"]: json.loads(l["conferencia_razao"]) for l in lotes if l["conferencia_razao"]},
                  pode_exportar=_pode(atual, ctx, "exportar"), pode_retorno=_pode(atual, ctx, "registrar_retorno"),
                  pode_conciliar=_pode(atual, ctx, "conciliar"),
                  itens={l["id"]: o.itens_lote(ctx.con, l["id"]) for l in lotes})


@router.post("/exportacao/gerar")
async def exportacao_gerar(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    p, c = str(f.get("periodo", "")), str(f.get("conta", ""))
    return tentar(atual, _u(ctx, f"/exportacao?periodo={p}&conta={c}"), lambda: o.gerar_lote(ctx, p, c),
                  lambda r: f"Lote {r['lote_id']} gerado com {r['quantidade']} lançamentos. Baixe e importe no Fortes (empresa de teste até a homologação).")


@router.post("/exportacao/lote/{lote_id}/{acao}")
async def exportacao_lote(lote_id: int, acao: str, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    l = ctx.con.execute("SELECT periodo, conta_banco FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if l is None:
        raise HTTPException(404)
    url = _u(ctx, f"/exportacao?periodo={l['periodo']}&conta={l['conta_banco']}")
    if acao == "retorno":
        aceito = f.get("resultado") == "aceito"
        return tentar(atual, url, lambda: o.registrar_retorno(ctx, lote_id, aceito, str(f.get("obs", ""))),
                      "Retorno registrado: aceito." if aceito else "Retorno registrado: rejeitado; os itens voltaram a 'classificado'.")
    if acao == "conferir":
        return tentar(atual, url, lambda: o.conferir_lote_no_razao(ctx, lote_id),
                      lambda r: "Conferência no Razão: " + ("aprovada." if r["aprovado"] else "há diferenças; veja o detalhe."))
    raise HTTPException(404)


@router.get("/exportacao/lote/{lote_id}/baixar")
def lote_baixar(lote_id: int, ctx=Depends(ctx_equipe)):
    try:
        bruto = o.arquivo_lote(ctx, lote_id)
    except o.OperacaoInvalida as exc:
        raise HTTPException(409, str(exc)) from None
    p = ctx.con.execute("SELECT periodo FROM lotes WHERE id = ?", (lote_id,)).fetchone()["periodo"]
    return Response(bruto, media_type="text/csv; charset=us-ascii",
                    headers={"Content-Disposition": f'attachment; filename="fortes_{p}_lote{lote_id}.csv"'})


@router.post("/exportacao/relatorio")
async def exportacao_relatorio(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    p, c = str(f.get("periodo", "")), str(f.get("conta", ""))
    try:
        arq = o.relatorio_pendencias(ctx, p, c)
        bruto = ctx.ler_arquivo(arq)
    except Exception as exc:  # noqa: BLE001
        return falhou(atual, _u(ctx, "/exportacao"), exc)
    return Response(bruto, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="pendencias_{re.sub(r"[^0-9-]", "", p)}.csv"'})


# ================================================================== cadastros

@router.get("/cadastros", response_class=HTMLResponse)
def cadastros(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    con = ctx.con
    return pagina(request, atual, "e_cadastros.html", emp=ctx.empresa, pode_cad=_pode(atual, ctx, "cadastrar"),
                  plano=con.execute("SELECT versao, COUNT(*) n, SUM(aceita_lancamento) a FROM plano_contas WHERE vigente = 1").fetchone(),
                  razao=con.execute("SELECT COUNT(*) n, MIN(data) i, MAX(data) f FROM razao").fetchone(),
                  regras=con.execute("SELECT * FROM regras WHERE ativa = 1 ORDER BY prioridade, id").fetchall(),
                  socios=o.termos_socios(con), contas=o.contas_analiticas(con), naturezas=o.NATUREZAS,
                  prefixo=ctx.prefixo, conta_padrao=parametro(con, "conta_banco_padrao"), limite=o.limite_historico(con))


@router.post("/cadastros/{acao}")
async def cadastros_acao(acao: str, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    url = _u(ctx, "/cadastros")
    arq = f.get("arquivo")
    bruto = await arq.read() if arq is not None and getattr(arq, "filename", None) else b""
    nome = getattr(arq, "filename", "") or ""
    s = lambda k: str(f.get(k, "")).strip()  # noqa: E731

    def com_arquivo(fn):
        def corpo():
            if not bruto:
                raise ErroEstrutural(["escolha um arquivo"])
            doc.validar_upload(nome, bruto)
            return fn()
        return corpo
    fns = {
        "plano": (com_arquivo(lambda: o.carregar_plano(ctx, nome, bruto)),
                  lambda r: f"Plano versão {r['versao']}: {r['contas']} contas, {r['analiticas']} analíticas."),
        "razao": (com_arquivo(lambda: o.carregar_razao(ctx, nome, bruto, s("formato") or "fortes_importacao",
                  {"data": s("c_data"), "conta": s("c_conta"), "debito": s("c_debito"), "credito": s("c_credito"),
                   "historico": s("c_hist") or None} if s("formato") == "tabular" else None)),
                  lambda r: f"Razão carregado: {r['partidas']} partidas."),
        "regras_json": (com_arquivo(lambda: o.importar_regras_json(ctx, bruto)),
                        lambda r: f"{r['criadas']} regra(s) importada(s)." + (f" Ignoradas: {'; '.join(r['ignoradas'][:10])}" if r["ignoradas"] else "")),
        "regra": (lambda: o.criar_regra(ctx, s("nome"), s("tipo"), s("padrao"), s("sentido"), s("conta"),
                                        int(s("prioridade") or 100), s("historico") or None, s("natureza") or "normal"),
                  "Regra criada."),
        "reaplicar": (lambda: o.reaplicar_regras(ctx), lambda n: f"{n} movimento(s) receberam proposta."),
        "socio": (lambda: o.adicionar_socio(ctx, s("termo")), "Sócio cadastrado."),
        "parametros": (lambda: (o.definir_prefixo(ctx, s("prefixo").upper()) if s("prefixo").upper() != ctx.prefixo else None,
                                o.definir_conta_banco_padrao(ctx, s("conta")) if s("conta") else None,
                                o.definir_limite_historico(ctx, int(s("limite"))) if s("limite").isdigit() and int(s("limite")) != o.limite_historico(ctx.con) else None),
                       "Parâmetros salvos."),
    }
    m = re.fullmatch(r"regra-(\d+)-desativar", acao)
    if m:
        return tentar(atual, url, lambda: o.desativar_regra(ctx, int(m.group(1))), "Regra desativada.")
    m = re.fullmatch(r"socio-remover", acao)
    if m:
        return tentar(atual, url, lambda: o.remover_socio(ctx, s("termo")), "Sócio removido.")
    if acao not in fns:
        raise HTTPException(404)
    fn, ok = fns[acao]
    return tentar(atual, url, fn, ok)


# ================================================================== solicitações ao cliente

@router.get("/solicitacoes", response_class=HTMLResponse)
def solicitacoes(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    return pagina(request, atual, "e_solicitacoes.html", emp=ctx.empresa, itens=doc.solicitacoes_visiveis(ctx),
                  docs={d["id"]: d for d in doc.listar(ctx)})


@router.post("/solicitacoes/criar")
async def solicitacoes_criar(request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    mid = str(f.get("movimento", "")).strip()
    return tentar(atual, _u(ctx, "/solicitacoes"),
                  lambda: doc.criar_solicitacao(ctx, str(f.get("mensagem", "")), int(mid) if mid.isdigit() else None),
                  "Solicitação enviada ao cliente.")


@router.post("/solicitacoes/{sid}/encerrar")
async def solicitacoes_encerrar(sid: int, request: Request, ctx=Depends(ctx_equipe), atual: Atual = Depends(atual_dep)):
    await ler_form(request, atual)
    return tentar(atual, _u(ctx, "/solicitacoes"), lambda: doc.encerrar_solicitacao(ctx, sid), "Solicitação encerrada.")
