"""Portal do cliente: /c/{slug}. O cliente envia documentos e responde solicitações; nada além disso."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from domain import documentos as doc
from domain import operacoes as o
from parsers.comum import ErroEstrutural
from storage.usuarios import AcessoNegado
from web.base import Atual, atual_dep, falhou, ler_form, nome_seguro, pagina, papel, tentar, voltar

router = APIRouter(prefix="/c/{slug}")
CATEGORIAS_CLIENTE = ("extrato", "planilha", "folha", "guia", "recibo", "contrato", "outro")


def ctx_cliente(slug: str, request: Request, atual: Atual = Depends(atual_dep)):
    try:
        ctx = o.Contexto.abrir(atual.central, atual.usuario, slug, request.app.state.data_dir)
    except AcessoNegado:
        raise HTTPException(404, "Empresa não encontrada") from None
    try:
        if papel(atual, ctx.empresa["id"]) != "cliente":
            raise HTTPException(403, "Esta área é do cliente")
        yield ctx
    finally:
        ctx.con.close()


@router.get("", response_class=HTMLResponse)
def portal(request: Request, ctx=Depends(ctx_cliente), atual: Atual = Depends(atual_dep)):
    # só campos explícitos: o cliente não vê observações internas nem nomes da equipe
    docs = [{"id": d["id"], "nome": d["nome_original"], "categoria": d["categoria"], "enviado_em": d["enviado_em"],
             "status": d["status"]} for d in doc.listar(ctx)]
    return pagina(request, atual, "portal.html", emp=ctx.empresa, docs=docs, categorias=CATEGORIAS_CLIENTE,
                  solic=doc.solicitacoes_visiveis(ctx))


@router.post("/enviar")
async def enviar(request: Request, ctx=Depends(ctx_cliente), atual: Atual = Depends(atual_dep)):
    if not request.app.state.limite.permitir(f"up:{atual.usuario['id']}", 20, 60):
        raise HTTPException(429, "Muitos envios em pouco tempo. Aguarde um minuto.")
    f = await ler_form(request, atual)
    arq, url = f.get("arquivo"), f"/c/{ctx.empresa['slug']}"
    try:
        if arq is None or not getattr(arq, "filename", None):
            raise ErroEstrutural(["escolha um arquivo"])
        cat = str(f.get("categoria", "outro"))
        if cat not in CATEGORIAS_CLIENTE:
            raise ErroEstrutural(["categoria inválida"])
        doc.enviar(ctx, arq.filename, await arq.read(), cat, str(f.get("descricao", "")))
    except Exception as exc:  # noqa: BLE001
        return falhou(atual, url, exc)
    return voltar(atual, url, ok="Arquivo enviado. Nossa equipe vai conferir.")


@router.post("/solicitacoes/{sid}/responder")
async def responder(sid: int, request: Request, ctx=Depends(ctx_cliente), atual: Atual = Depends(atual_dep)):
    f = await ler_form(request, atual)
    d = str(f.get("documento_id", "")).strip()
    return tentar(atual, f"/c/{ctx.empresa['slug']}",
                  lambda: doc.responder_solicitacao(ctx, sid, str(f.get("texto", "")), int(d) if d.isdigit() else None),
                  "Resposta enviada.")


@router.get("/documentos/{doc_id}/baixar")
def baixar(doc_id: int, ctx=Depends(ctx_cliente)):
    try:
        d, bruto = doc.obter(ctx, doc_id)  # cliente só abre o que ele mesmo enviou
    except o.OperacaoInvalida:
        raise HTTPException(404, "Documento não encontrado") from None
    return Response(bruto, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{nome_seguro(d["nome_original"])}"'})
