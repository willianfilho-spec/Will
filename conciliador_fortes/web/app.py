"""Conciliador Fortes — web app (FastAPI). Criado por `criar_app()`.

Rotas públicas: /login, /static. Todo o resto exige sessão válida e, quando exigido, 2FA.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import config
from domain import homologacao as hom
from storage import audit, usuarios
from storage.audit import registrar_acesso
from storage.database import conectar_empresa
from web import equipe, portal
from web import seguranca as sg
from web.base import (COOKIE, Atual, Redireciona, atual_dep, atual_pendente_dep, atual_pre_mfa_dep, get_central,
                      ip_de, ler_form, pagina, tentar, templates, voltar, falhou)

log = logging.getLogger("conciliador.web")
COOKIE_LOGIN = "cf_login"


def _cookie(resp: Response, nome: str, valor: str, **kw) -> None:
    resp.set_cookie(nome, valor, httponly=True, secure=config.COOKIE_SEGURO, samesite="strict", path="/", **kw)


def criar_app(data_dir: Path | None = None, dica_login: str | None = None) -> FastAPI:
    app = FastAPI(title="Conciliador Fortes", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    app.state.limite = sg.LimiteRequisicoes()
    app.state.dica_login = dica_login  # só no modo de teste local; nunca em produção
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(equipe.router)
    app.include_router(portal.router)

    # ---------------------------------------------------------------- middlewares
    @app.middleware("http")
    async def protecoes(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > config.MAX_UPLOAD_BYTES + 1_000_000:
            resp: Response = PlainTextResponse("Arquivo grande demais.", status_code=413)
        else:
            try:
                resp = await call_next(request)
            except Redireciona as exc:
                resp = RedirectResponse(exc.url, 303)
            except Exception:  # noqa: BLE001
                log.exception("erro não tratado em %s", request.url.path)
                resp = PlainTextResponse("Erro interno. Nada foi exibido por segurança.", status_code=500)
        for k, v in sg.cabecalhos().items():
            resp.headers[k] = v
        if request.url.path.startswith("/static"):
            resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @app.exception_handler(Redireciona)
    async def _redir(request: Request, exc: Redireciona):
        return RedirectResponse(exc.url, 303)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        textos = {403: "Acesso negado.", 404: "Não encontrado.", 429: "Muitas requisições."}
        return templates.TemplateResponse(request, "erro.html", {"codigo": exc.status_code, "atual": None, "flash": None,
                                          "usuario": None, "csrf": "",
                                          "texto": exc.detail if exc.status_code in (403, 404, 409, 429) and isinstance(exc.detail, str) else textos.get(exc.status_code, "Erro.")},
                                          status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError):
        return PlainTextResponse("Requisição inválida.", status_code=422)

    @app.get("/saude", include_in_schema=False)
    def saude():
        """Verificação de saúde para a plataforma (sem login, sem dados). Confere que o banco central abre."""
        from storage.database import conectar_central
        try:
            conectar_central(app.state.data_dir).close()
        except Exception:  # noqa: BLE001
            return PlainTextResponse("erro", status_code=503)
        return PlainTextResponse("ok")

    # ---------------------------------------------------------------- login
    def _login_page(request: Request, erro: str | None = None, status: int = 200):
        token = secrets.token_urlsafe(24)
        resp = templates.TemplateResponse(request, "login.html", {"atual": None, "usuario": None, "flash": None, "csrf": "",
                                          "csrf_login": token, "erro": erro, "dica": app.state.dica_login}, status_code=status)
        _cookie(resp, COOKIE_LOGIN, token, max_age=900)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def raiz():
        return RedirectResponse("/painel", 303)

    @app.get("/login", response_class=HTMLResponse)
    def login_get(request: Request):
        return _login_page(request)

    @app.post("/login")
    async def login_post(request: Request, central=Depends(get_central)):
        ip = ip_de(request)
        form = await request.form()
        esperado = request.cookies.get(COOKIE_LOGIN, "")
        if not esperado or not hmac.compare_digest(str(form.get("csrf_login", "")), esperado):
            return _login_page(request, "Sessão do formulário expirou. Tente de novo.", 400)
        if not app.state.limite.permitir(f"login:{ip}", 10, 60):
            return _login_page(request, "Muitas tentativas por minuto. Aguarde.", 429)
        u, erro = sg.tentar_login(central, str(form.get("email", "")), str(form.get("senha", "")), ip)
        if u is None:
            return _login_page(request, erro, 401)
        sg.limpar_sessoes_vencidas(central)
        token, _ = sg.criar_sessao(central, u["id"], not u["totp_ativo"], ip)
        registrar_acesso(central, u["id"], None, "login", "ok", ip=ip, mfa_pendente=bool(u["totp_ativo"]))
        resp = RedirectResponse("/painel", 303)
        _cookie(resp, COOKIE, token)
        resp.delete_cookie(COOKIE_LOGIN, path="/")
        return resp

    @app.post("/logout")
    async def logout(request: Request, atual: Atual = Depends(atual_pre_mfa_dep)):
        await ler_form(request, atual)
        sg.encerrar_sessao(atual.central, atual.sessao.token_hash)
        registrar_acesso(atual.central, atual.usuario["id"], None, "logout", "ok", ip=atual.ip)
        resp = RedirectResponse("/login", 303)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    # ---------------------------------------------------------------- 2FA no login
    @app.get("/2fa", response_class=HTMLResponse)
    def mfa_get(request: Request, atual: Atual = Depends(atual_pre_mfa_dep)):
        if atual.sessao.mfa_ok or not atual.usuario["totp_ativo"]:
            return RedirectResponse("/painel", 303)
        return pagina(request, atual, "mfa.html")

    @app.post("/2fa")
    async def mfa_post(request: Request, atual: Atual = Depends(atual_pre_mfa_dep)):
        f = await ler_form(request, atual)
        u, c = atual.usuario, atual.central
        chave = f"m:{u['id']}"
        if sg.minutos_bloqueado(c, chave):
            return voltar(atual, "/2fa", erro=["Muitas tentativas. Aguarde alguns minutos."])
        codigo, ok = str(f.get("codigo", "")).strip(), False
        passo = sg.verificar_totp(sg.segredo_do_usuario(u), codigo, u["totp_ultimo_passo"])
        if passo is not None:
            c.execute("UPDATE usuarios SET totp_ultimo_passo = ? WHERE id = ?", (passo, u["id"]))
            ok = True
        elif sg.usar_codigo_recuperacao(c, u["id"], codigo):
            ok = True
            registrar_acesso(c, u["id"], None, "2fa_codigo_recuperacao", "ok", ip=atual.ip)
        if not ok:
            sg.registrar_falha(c, chave, config.MAX_FALHAS_LOGIN)
            registrar_acesso(c, u["id"], None, "2fa", "negado", ip=atual.ip)
            return voltar(atual, "/2fa", erro=["Código incorreto."])
        sg.limpar_falhas(c, chave)
        token = sg.promover_sessao(c, atual.sessao, atual.ip)
        registrar_acesso(c, u["id"], None, "2fa", "ok", ip=atual.ip)
        resp = RedirectResponse("/painel", 303)
        _cookie(resp, COOKIE, token)
        return resp

    # ---------------------------------------------------------------- painel
    @app.get("/painel", response_class=HTMLResponse)
    def painel(request: Request, atual: Atual = Depends(atual_dep)):
        emps = usuarios.empresas_do_usuario(atual.central, atual.usuario["id"])
        itens = [{"emp": e, "papel": usuarios.papel_na_empresa(atual.central, atual.usuario["id"], e["id"])} for e in emps]
        return pagina(request, atual, "painel.html", itens=itens)

    # ---------------------------------------------------------------- conta: senha e 2FA
    @app.get("/conta", response_class=HTMLResponse)
    def conta(request: Request, atual: Atual = Depends(atual_pendente_dep)):
        u, pend = atual.usuario, atual.sessao.totp_pendente
        seg = pend
        if not u["totp_ativo"] and not seg:
            seg = sg.novo_segredo()
            atual.central.execute("UPDATE sessoes SET totp_pendente = ? WHERE token_hash = ?", (seg, atual.sessao.token_hash))
        return pagina(request, atual, "conta.html", segredo=seg if not u["totp_ativo"] else None,
                      uri=sg.uri_totp(seg, u["email"]) if seg and not u["totp_ativo"] else None,
                      forcar_senha=bool(u["deve_trocar_senha"]), forcar_2fa=sg.exige_2fa(u) and not u["totp_ativo"],
                      pode_desativar=not sg.exige_2fa(u), codigos=None)

    @app.post("/conta/senha")
    async def conta_senha(request: Request, atual: Atual = Depends(atual_pendente_dep)):
        f = await ler_form(request, atual)
        u, c = atual.usuario, atual.central

        def fn():
            nova = str(f.get("nova", ""))
            if nova != str(f.get("confirmar", "")):
                raise ValueError("a confirmação não confere com a nova senha")
            if not app.state.limite.permitir(f"senha:{u['id']}", 5, 300):
                raise ValueError("muitas tentativas; aguarde alguns minutos")
            if not usuarios.conferir_senha(str(f.get("atual", "")), u["senha_hash"]):
                raise ValueError("a senha atual está incorreta")
            sg.validar_politica_senha(nova, u["email"], u["nome"])
            if usuarios.conferir_senha(nova, u["senha_hash"]):
                raise ValueError("a nova senha deve ser diferente da atual")
            c.execute("UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 0, senha_alterada_em = datetime('now') WHERE id = ?",
                      (usuarios.hash_senha(nova), u["id"]))
            sg.encerrar_todas(c, u["id"], exceto=atual.sessao.token_hash)  # derruba as outras sessões
            registrar_acesso(c, u["id"], None, "senha_alterada", "ok", ip=atual.ip)
        return tentar(atual, "/conta", fn, "Senha alterada. As outras sessões foram encerradas.")

    @app.post("/conta/2fa")
    async def conta_2fa(request: Request, atual: Atual = Depends(atual_pendente_dep)):
        f = await ler_form(request, atual)
        u, c = atual.usuario, atual.central
        if u["totp_ativo"] or not atual.sessao.totp_pendente:
            return voltar(atual, "/conta", erro=["Nada a ativar."])
        seg = atual.sessao.totp_pendente
        passo = sg.verificar_totp(seg, str(f.get("codigo", "")), 0)
        if passo is None:
            return voltar(atual, "/conta", erro=["Código incorreto. Confira o horário do celular e tente de novo."])
        codigos = sg.ativar_totp(c, u["id"], seg)
        c.execute("UPDATE usuarios SET totp_ultimo_passo = ? WHERE id = ?", (passo, u["id"]))
        c.execute("UPDATE sessoes SET totp_pendente = NULL, mfa_ok = 1 WHERE token_hash = ?", (atual.sessao.token_hash,))
        registrar_acesso(c, u["id"], None, "2fa_ativado", "ok", ip=atual.ip)
        u2 = c.execute("SELECT * FROM usuarios WHERE id = ?", (u["id"],)).fetchone()
        atual2 = Atual(c, atual.sessao, u2, atual.ip)
        return pagina(request, atual2, "conta.html", segredo=None, uri=None, forcar_senha=False, forcar_2fa=False,
                      pode_desativar=not sg.exige_2fa(u2), codigos=codigos)

    @app.post("/conta/2fa/desativar")
    async def conta_2fa_off(request: Request, atual: Atual = Depends(atual_pendente_dep)):
        await ler_form(request, atual)
        if sg.exige_2fa(atual.usuario):
            return voltar(atual, "/conta", erro=["Para a equipe o 2FA é obrigatório."])
        sg.desativar_totp(atual.central, atual.usuario["id"])
        registrar_acesso(atual.central, atual.usuario["id"], None, "2fa_desativado", "ok", ip=atual.ip)
        return voltar(atual, "/conta", ok="2FA desativado.")

    # ---------------------------------------------------------------- administração
    def admin_dep(atual: Atual = Depends(atual_dep)) -> Atual:
        if atual.usuario["papel_global"] != "admin":
            raise HTTPException(403, "Área do administrador")
        return atual

    def _dados_admin(atual: Atual) -> dict:
        c = atual.central
        agora = __import__("time").time()
        bloq = {r["chave"] for r in c.execute("SELECT chave FROM tentativas_login WHERE bloqueado_ate > ?", (agora,))}
        us = c.execute("SELECT id, nome, email, papel_global, ativo, totp_ativo, deve_trocar_senha FROM usuarios ORDER BY nome").fetchall()
        return {"us": [dict(u, bloqueado=sg._chave_email(u["email"]) in bloq) for u in us],
                "emps": c.execute("SELECT * FROM empresas ORDER BY razao_social").fetchall(),
                "perms": c.execute("SELECT u.nome, e.razao_social, p.papel_empresa, p.usuario_id, p.empresa_id FROM permissoes_empresa p "
                                   "JOIN usuarios u ON u.id = p.usuario_id JOIN empresas e ON e.id = p.empresa_id "
                                   "ORDER BY u.nome").fetchall(),
                "hom": hom.estado(c), "itens_hom": hom.ITENS, "liberada": hom.integracao_liberada(c),
                "acessos": c.execute("SELECT * FROM audit_acesso ORDER BY id DESC LIMIT 60").fetchall(),
                "papeis_globais": config.PAPEIS_GLOBAIS, "papeis_empresa": config.PAPEIS_EMPRESA}

    @app.get("/admin", response_class=HTMLResponse)
    def admin(request: Request, atual: Atual = Depends(admin_dep)):
        return pagina(request, atual, "admin.html", senha_gerada=None, **_dados_admin(atual))

    @app.post("/admin/{acao}")
    async def admin_acao(acao: str, request: Request, atual: Atual = Depends(admin_dep)):
        f = await ler_form(request, atual)
        c, s = atual.central, lambda k: str(f.get(k, "")).strip()  # noqa: E731
        reg = lambda a, **kw: registrar_acesso(c, atual.usuario["id"], None, a, "ok", ip=atual.ip, **kw)  # noqa: E731

        if acao == "usuario":
            try:
                temp = sg.senha_temporaria()
                uid = usuarios.criar_usuario(c, s("nome"), s("email"), temp, s("papel"))
                c.execute("UPDATE usuarios SET deve_trocar_senha = 1 WHERE id = ?", (uid,))
                reg("usuario_criado", usuario=uid, papel=s("papel"))
            except Exception as exc:  # noqa: BLE001
                return falhou(atual, "/admin", exc)
            sg.tirar_flash(c, atual.sessao)
            return pagina(request, atual, "admin.html", senha_gerada={"email": s("email"), "senha": temp}, **_dados_admin(atual))
        if acao == "empresa":
            def fn():
                lim = __import__("domain.money", fromlist=["x"]).para_centavos(s("limite") or "10000,00")
                usuarios.criar_empresa(c, s("slug").lower(), s("razao"), s("cnpj"), lim, request.app.state.data_dir)
                reg("empresa_criada", slug=s("slug"))
            return tentar(atual, "/admin", fn, "Empresa criada, com banco e pasta próprios.")
        if acao == "permissao":
            def fn():
                usuarios.conceder(c, int(s("usuario")), int(s("empresa")), s("papel"))
                reg("permissao_concedida", usuario=s("usuario"), empresa=s("empresa"), papel=s("papel"))
            return tentar(atual, "/admin", fn, "Permissão gravada.")
        if acao == "revogar":
            def fn():
                c.execute("DELETE FROM permissoes_empresa WHERE usuario_id = ? AND empresa_id = ?", (int(s("usuario")), int(s("empresa"))))
                reg("permissao_revogada", usuario=s("usuario"), empresa=s("empresa"))
            return tentar(atual, "/admin", fn, "Permissão revogada.")
        if acao == "desbloquear":
            sg.desbloquear_usuario(c, s("email"))
            reg("login_desbloqueado", email=s("email"))
            return voltar(atual, "/admin", ok="Login desbloqueado.")
        if acao in ("reset2fa", "desativar", "reativar", "resetsenha"):
            uid = int(s("usuario") or 0)
            if uid == atual.usuario["id"] and acao in ("desativar", "reset2fa"):
                return voltar(atual, "/admin", erro=["Você não pode fazer isso na sua própria conta."])
            if acao == "reset2fa":
                sg.desativar_totp(c, uid)
                sg.encerrar_todas(c, uid)
            elif acao == "desativar":
                c.execute("UPDATE usuarios SET ativo = 0 WHERE id = ?", (uid,))
                sg.encerrar_todas(c, uid)
            elif acao == "reativar":
                c.execute("UPDATE usuarios SET ativo = 1 WHERE id = ?", (uid,))
            else:
                temp = sg.senha_temporaria()
                c.execute("UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 1 WHERE id = ?", (usuarios.hash_senha(temp), uid))
                sg.encerrar_todas(c, uid)
                reg("senha_redefinida", usuario=uid)
                u = c.execute("SELECT email FROM usuarios WHERE id = ?", (uid,)).fetchone()
                return pagina(request, atual, "admin.html", senha_gerada={"email": u["email"], "senha": temp}, **_dados_admin(atual))
            reg(f"usuario_{acao}", usuario=uid)
            return voltar(atual, "/admin", ok="Feito.")
        if acao == "homologacao":
            arq = f.get("evidencia")
            bruto = await arq.read() if arq is not None and getattr(arq, "filename", None) else None
            return tentar(atual, "/admin", lambda: hom.registrar(
                c, atual.usuario, s("item"), s("status"), s("teste"), s("resultado"), s("falha"), s("acao_corretiva"),
                getattr(arq, "filename", None), bruto, s("referencia"), request.app.state.data_dir), "Resultado registrado.")
        if acao == "auditoria":
            prob = audit.verificar_cadeia(c, "audit_acesso")
            return (voltar(atual, "/admin", ok="Cadeia de auditoria de acesso íntegra.") if not prob
                    else voltar(atual, "/admin", erro=prob, titulo="Cadeia de auditoria com problema:"))
        raise HTTPException(404)

    return app


app = None  # use `criar_app()`; veja scripts/rodar_web.py
