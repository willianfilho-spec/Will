"""Documentos enviados (cliente ou equipe) e solicitações da equipe ao cliente.

O cliente só envia e responde: nunca vê movimentos, contas, regras ou lançamentos. Cada cliente vê só
os próprios envios; as solicitações da empresa são visíveis a todos os clientes dela. Nada enviado
pelo cliente vira lançamento sozinho: a equipe decide processar.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import config
from domain import deduplicator
from domain.operacoes import Contexto, OperacaoInvalida, carregar_extrato
from parsers.comum import ErroEstrutural, sanitizar_texto
from storage import audit
from storage.database import agora, transacao

CATEGORIAS = ("extrato", "planilha", "folha", "guia", "recibo", "contrato", "lancamentos", "razao", "outro")
PERMITIDAS = {".ofx", ".csv", ".txt", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".json"}


def validar_upload(nome: str, bruto: bytes) -> str:
    """Confere tamanho, extensão e conteúdo (assinatura). Devolve a extensão. Não confia no tipo informado."""
    if not bruto:
        raise ErroEstrutural(["arquivo vazio"])
    if len(bruto) > config.MAX_UPLOAD_BYTES:
        raise ErroEstrutural([f"arquivo acima do limite de {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB"])
    ext = Path(nome or "").suffix.lower()
    if ext not in PERMITIDAS:
        raise ErroEstrutural([f"extensão {ext or '(nenhuma)'} não permitida; use: {', '.join(sorted(PERMITIDAS))}"])
    cab = bruto[:16]
    ok = {
        ".pdf": cab.startswith(b"%PDF"),
        ".png": cab.startswith(b"\x89PNG"),
        ".jpg": cab.startswith(b"\xff\xd8\xff"), ".jpeg": cab.startswith(b"\xff\xd8\xff"),
        ".xlsx": cab.startswith(b"PK\x03\x04"),
    }.get(ext)
    if ok is None:  # formatos de texto
        ok = b"\x00" not in bruto[:4096] and not bruto.lstrip().startswith((b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF"))
        if ext == ".ofx":
            ok = ok and (b"<OFX" in bruto[:4096].upper() or b"OFXHEADER" in bruto[:200].upper())
    if not ok:
        raise ErroEstrutural([f"o conteúdo não corresponde à extensão {ext}"])
    return ext


def enviar(ctx: Contexto, nome: str, bruto: bytes, categoria: str, descricao: str = "") -> int:
    ctx.exigir("enviar_documento")
    if categoria not in CATEGORIAS:
        raise OperacaoInvalida("categoria inválida")
    ext = validar_upload(nome, bruto)
    sha = deduplicator.sha256(bruto)
    origem = "cliente" if _papel(ctx) == "cliente" else "equipe"
    with transacao(ctx.con):
        rep = ctx.con.execute("SELECT id, enviado_em FROM documentos WHERE sha256 = ? AND usuario_id = ?",
                              (sha, ctx.usuario["id"])).fetchone()
        if rep:
            raise ErroEstrutural([f"você já enviou este arquivo em {rep['enviado_em']} (documento {rep['id']})"])
        uid = uuid.uuid4().hex
        destino = ctx.pasta / "arquivos" / "originais" / f"doc_{uid}{ext}"
        ctx.gravar_arquivo(destino, bruto)
        cur = ctx.con.execute(
            "INSERT INTO documentos (uuid, nome_original, categoria, descricao, sha256, tamanho, caminho, origem, "
            "enviado_por, usuario_id, enviado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, sanitizar_texto(nome)[:200], categoria, sanitizar_texto(descricao)[:500] or None, sha, len(bruto),
             str(destino.relative_to(ctx.pasta)), origem, ctx.nome, ctx.usuario["id"], agora()))
        audit.registrar(ctx.con, ctx.nome, "documento_enviado", "documento", cur.lastrowid, nome=nome,
                        categoria=categoria, sha256=sha, tamanho=len(bruto), origem=origem)
    return cur.lastrowid


def _papel(ctx: Contexto) -> str | None:
    from storage.usuarios import papel_na_empresa
    return papel_na_empresa(ctx.central, ctx.usuario["id"], ctx.empresa["id"])


def _eh_cliente(ctx: Contexto) -> bool:
    return _papel(ctx) == "cliente"


def listar(ctx: Contexto) -> list[sqlite3.Row]:
    ctx.exigir("enviar_documento")
    if _eh_cliente(ctx):
        return ctx.con.execute("SELECT * FROM documentos WHERE usuario_id = ? ORDER BY id DESC",
                               (ctx.usuario["id"],)).fetchall()
    return ctx.con.execute("SELECT * FROM documentos ORDER BY id DESC").fetchall()


def obter(ctx: Contexto, doc_id: int) -> tuple[sqlite3.Row, bytes]:
    """Cliente só abre o que ele mesmo enviou. Documento de outro cliente (ou inexistente) = 'não existe'."""
    ctx.exigir("enviar_documento")
    d = ctx.con.execute("SELECT * FROM documentos WHERE id = ?", (doc_id,)).fetchone()
    if d is None or (_eh_cliente(ctx) and d["usuario_id"] != ctx.usuario["id"]):
        raise OperacaoInvalida("documento não encontrado")
    bruto = ctx.ler_arquivo(ctx.pasta / d["caminho"])
    if deduplicator.sha256(bruto) != d["sha256"]:
        with transacao(ctx.con):
            audit.registrar(ctx.con, ctx.nome, "documento_adulterado", "documento", doc_id)
        raise OperacaoInvalida("o documento foi alterado depois do envio (SHA-256 diferente); não use")
    return d, bruto


def processar_extrato(ctx: Contexto, doc_id: int, conta_banco: str, mapa=None) -> dict:
    ctx.exigir("processar_documento")
    d, bruto = obter(ctx, doc_id)
    if d["status"] != "recebido":
        raise OperacaoInvalida(f"documento já {d['status']}")
    r = carregar_extrato(ctx, d["nome_original"], bruto, conta_banco, mapa)
    with transacao(ctx.con):
        ctx.con.execute("UPDATE documentos SET status = 'processado', observacao = ? WHERE id = ?",
                        (f"Processado por {ctx.nome}: {r['movimentos']} movimentos", doc_id))
        audit.registrar(ctx.con, ctx.nome, "documento_processado", "documento", doc_id, movimentos=r["movimentos"])
    return r


def recusar(ctx: Contexto, doc_id: int, motivo: str) -> None:
    ctx.exigir("processar_documento")
    if len(motivo.strip()) < 5:
        raise OperacaoInvalida("informe o motivo")
    with transacao(ctx.con):
        d = ctx.con.execute("SELECT status FROM documentos WHERE id = ?", (doc_id,)).fetchone()
        if d is None or d["status"] != "recebido":
            raise OperacaoInvalida("documento inexistente ou já tratado")
        ctx.con.execute("UPDATE documentos SET status = 'recusado', observacao = ? WHERE id = ?",
                        (f"Recusado por {ctx.nome}: {sanitizar_texto(motivo)}", doc_id))
        audit.registrar(ctx.con, ctx.nome, "documento_recusado", "documento", doc_id, motivo=motivo)


# ------------------------------------------------------------------ solicitações

def criar_solicitacao(ctx: Contexto, mensagem: str, movimento_id: int | None = None) -> int:
    ctx.exigir("criar_solicitacao")
    if len(mensagem.strip()) < 5:
        raise OperacaoInvalida("escreva o que precisa do cliente")
    with transacao(ctx.con):
        if movimento_id is not None and ctx.con.execute("SELECT 1 FROM movimentos WHERE id = ?", (movimento_id,)).fetchone() is None:
            raise OperacaoInvalida("movimento inexistente")
        cur = ctx.con.execute("INSERT INTO solicitacoes (movimento_id, mensagem, criada_por, criada_em) VALUES (?, ?, ?, ?)",
                              (movimento_id, sanitizar_texto(mensagem)[:1000], ctx.nome, agora()))
        audit.registrar(ctx.con, ctx.nome, "solicitacao_criada", "solicitacao", cur.lastrowid, movimento_id=movimento_id)
    return cur.lastrowid


def solicitacoes_visiveis(ctx: Contexto) -> list[dict]:
    """O cliente vê só a mensagem e o próprio retorno, sem dados do movimento."""
    ctx.exigir("responder_solicitacao")
    linhas = ctx.con.execute("SELECT * FROM solicitacoes ORDER BY id DESC").fetchall()
    if _eh_cliente(ctx):
        return [{"id": r["id"], "mensagem": r["mensagem"], "status": r["status"], "criada_em": r["criada_em"],
                 "resposta": r["resposta"], "respondida_em": r["respondida_em"]} for r in linhas]
    return [dict(r) for r in linhas]


def responder_solicitacao(ctx: Contexto, sol_id: int, texto: str, documento_id: int | None = None) -> None:
    ctx.exigir("responder_solicitacao")
    if len(texto.strip()) < 2:
        raise OperacaoInvalida("escreva a resposta")
    with transacao(ctx.con):
        s = ctx.con.execute("SELECT * FROM solicitacoes WHERE id = ?", (sol_id,)).fetchone()
        if s is None or s["status"] == "encerrada":
            raise OperacaoInvalida("solicitação inexistente ou encerrada")
        if documento_id is not None:
            d = ctx.con.execute("SELECT usuario_id FROM documentos WHERE id = ?", (documento_id,)).fetchone()
            if d is None or (_eh_cliente(ctx) and d["usuario_id"] != ctx.usuario["id"]):
                raise OperacaoInvalida("documento não encontrado")
        ctx.con.execute("UPDATE solicitacoes SET status = 'respondida', resposta = ?, respondida_por = ?, "
                        "respondida_em = ?, documento_id = ? WHERE id = ?",
                        (sanitizar_texto(texto)[:2000], ctx.nome, agora(), documento_id, sol_id))
        audit.registrar(ctx.con, ctx.nome, "solicitacao_respondida", "solicitacao", sol_id, documento_id=documento_id)


def encerrar_solicitacao(ctx: Contexto, sol_id: int) -> None:
    ctx.exigir("criar_solicitacao")
    with transacao(ctx.con):
        s = ctx.con.execute("SELECT status FROM solicitacoes WHERE id = ?", (sol_id,)).fetchone()
        if s is None or s["status"] == "encerrada":
            raise OperacaoInvalida("solicitação inexistente ou já encerrada")
        ctx.con.execute("UPDATE solicitacoes SET status = 'encerrada', encerrada_por = ?, encerrada_em = ? WHERE id = ?",
                        (ctx.nome, agora(), sol_id))
        audit.registrar(ctx.con, ctx.nome, "solicitacao_encerrada", "solicitacao", sol_id)


def marcar_processado(ctx: Contexto, doc_id: int, observacao: str) -> None:
    ctx.exigir("processar_documento")
    with transacao(ctx.con):
        ctx.con.execute("UPDATE documentos SET status = 'processado', observacao = ? WHERE id = ? AND status = 'recebido'",
                        (f"{sanitizar_texto(observacao)} (por {ctx.nome})", doc_id))
        audit.registrar(ctx.con, ctx.nome, "documento_processado", "documento", doc_id)
