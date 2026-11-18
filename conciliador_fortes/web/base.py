"""Infraestrutura do web app: dependências, CSRF, mensagens e renderização."""

from __future__ import annotations

import hmac
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from domain import operacoes as o
from domain.money import ValorInvalido, formatar_br
from exporters.fortes_exporter import LoteBloqueado
from parsers.comum import ErroEstrutural
from storage import cripto
from storage.database import conectar_central
from storage.usuarios import AcessoNegado, papel_na_empresa
from web import seguranca as sg

log = logging.getLogger("conciliador.web")
COOKIE = "cf_sessao"
EQUIPE = ("operador", "revisor", "aprovador")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["brl"] = lambda v: formatar_br(int(v or 0))
templates.env.filters["brl0"] = lambda v: formatar_br(int(v or 0), simbolo=False)


class Redireciona(Exception):
    def __init__(self, url: str):
        self.url = url


@dataclass
class Atual:
    central: sqlite3.Connection
    sessao: sg.Sessao
    usuario: sqlite3.Row
    ip: str


def ip_de(request: Request) -> str:
    return request.client.host if request.client else "?"


def get_central(request: Request):
    con = conectar_central(request.app.state.data_dir)
    try:
        yield con
    finally:
        con.close()


def _atual(request: Request, central, exigir_mfa: bool, permitir_pendente: bool) -> Atual:
    s = sg.obter_sessao(central, request.cookies.get(COOKIE))
    if s is None:
        raise Redireciona("/login")
    u = central.execute("SELECT * FROM usuarios WHERE id = ? AND ativo = 1", (s.usuario_id,)).fetchone()
    if u is None:
        sg.encerrar_sessao(central, s.token_hash)
        raise Redireciona("/login")
    if exigir_mfa and u["totp_ativo"] and not s.mfa_ok:
        raise Redireciona("/2fa")
    if not permitir_pendente:
        if u["deve_trocar_senha"]:
            raise Redireciona("/conta")
        if sg.exige_2fa(u) and not u["totp_ativo"]:
            raise Redireciona("/conta")
    return Atual(central, s, u, ip_de(request))


async def ler_form(request: Request, atual: Atual):
    """Lê o formulário e confere o token CSRF da sessão. Sem token válido, nada é executado."""
    form = await request.form()
    if not hmac.compare_digest(str(form.get("csrf", "")), atual.sessao.csrf):
        raise HTTPException(403, "Falha de segurança: recarregue a página e tente de novo.")
    return form


def mensagens_de(exc: Exception) -> list[str] | None:
    if isinstance(exc, (ErroEstrutural, LoteBloqueado)):
        return list(exc.problemas)
    if isinstance(exc, AcessoNegado):
        return [f"Sem permissão: {exc}"]
    if isinstance(exc, (o.OperacaoInvalida, ValorInvalido, ValueError, sqlite3.IntegrityError, cripto.ErroCripto)):
        texto = str(exc)
        return [re.sub(r"^.*?(abort|ABORT)[^:]*:\s*", "", texto) or texto]
    return None


def voltar(atual: Atual, url: str, ok: str | None = None, erro: list[str] | None = None, titulo: str | None = None):
    if erro:
        sg.definir_flash(atual.central, atual.sessao.token_hash, "erro", ([titulo] if titulo else []) + erro)
    elif ok:
        sg.definir_flash(atual.central, atual.sessao.token_hash, "ok", [ok])
    return RedirectResponse(url, 303)


def tentar(atual: Atual, url: str, fn, ok):
    """Executa a operação; erro de negócio vira mensagem legível, nunca stack trace."""
    try:
        r = fn()
    except Redireciona:
        raise
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        msgs = mensagens_de(exc)
        if msgs is None:
            log.exception("erro inesperado")
            return voltar(atual, url, erro=["Erro inesperado. Nada foi gravado; avise o administrador."])
        return voltar(atual, url, erro=msgs, titulo="Não foi possível concluir:")
    return voltar(atual, url, ok=ok(r) if callable(ok) else ok)


def falhou(atual: Atual, url: str, exc: Exception):
    """Converte uma exceção já capturada em mensagem (mesma regra de `tentar`)."""
    if isinstance(exc, (Redireciona, HTTPException)):
        raise exc
    msgs = mensagens_de(exc)
    if msgs is None:
        log.error("erro inesperado", exc_info=exc)
        return voltar(atual, url, erro=["Erro inesperado. Nada foi gravado; avise o administrador."])
    return voltar(atual, url, erro=msgs, titulo="Não foi possível concluir:")


def pagina(request: Request, atual: Atual | None, nome: str, **ctx):
    flash = sg.tirar_flash(atual.central, atual.sessao) if atual else None
    from domain import homologacao
    base = {"atual": atual, "usuario": atual.usuario if atual else None, "csrf": atual.sessao.csrf if atual else "",
            "flash": flash}
    if atual:
        base["homologada"] = homologacao.integracao_liberada(atual.central)
    return templates.TemplateResponse(request, nome, {**base, **ctx})


def papel(atual: Atual, empresa_id: int) -> str | None:
    return papel_na_empresa(atual.central, atual.usuario["id"], empresa_id)


def nome_seguro(nome: str) -> str:
    return re.sub(r"[^\w.\-]", "_", nome or "arquivo")[:120] or "arquivo"


# ---- dependências (FastAPI) ---------------------------------------------------------------
from fastapi import Depends  # noqa: E402


def atual_dep(request: Request, central: sqlite3.Connection = Depends(get_central)) -> Atual:
    return _atual(request, central, exigir_mfa=True, permitir_pendente=False)


def atual_pendente_dep(request: Request, central: sqlite3.Connection = Depends(get_central)) -> Atual:
    """Para as páginas da conta: permite entrar mesmo com troca de senha/2FA pendentes."""
    return _atual(request, central, exigir_mfa=True, permitir_pendente=True)


def atual_pre_mfa_dep(request: Request, central: sqlite3.Connection = Depends(get_central)) -> Atual:
    return _atual(request, central, exigir_mfa=False, permitir_pendente=True)
