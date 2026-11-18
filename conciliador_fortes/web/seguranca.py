"""Segurança do web app: sessões, bloqueio de login, 2FA, política de senha, limite de requisições.

Decisões:
- Sessão no servidor (central.db). O cookie só leva um token aleatório; o banco guarda o SHA-256 dele,
  então vazar o banco não entrega sessões abertas.
- Expira por inatividade (30 min) e por tempo total (8 h). O token muda depois do 2FA.
- Bloqueio de login por e-mail (5 falhas = 15 min) e por IP, sem revelar se a conta existe.
  Efeito colateral aceito: alguém pode bloquear a conta de outra pessoa por 15 min; o administrador desbloqueia.
- 2FA TOTP (RFC 6238, SHA-1, 6 dígitos, 30 s), sem reutilização de código, mais 8 códigos de recuperação.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import config
from storage import cripto
from storage.audit import registrar_acesso
from storage.usuarios import conferir_senha, hash_senha

SENHAS_COMUNS = {"senha12345", "1234567890", "password123", "qwerty12345", "123456789a", "admin12345",
                 "contabil123", "mudar12345", "trocar12345", "fortes12345", "letmein1234"}
_HASH_FALSO = hash_senha("senha-falsa-para-igualar-o-tempo")


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


# ------------------------------------------------------------------ senha

def validar_politica_senha(senha: str, email: str = "", nome: str = "") -> None:
    erros = []
    if len(senha) < config.SENHA_MINIMA:
        erros.append(f"mínimo de {config.SENHA_MINIMA} caracteres")
    if senha.lower() in SENHAS_COMUNS or len(set(senha)) < 4:
        erros.append("senha comum ou com poucos caracteres diferentes")
    if sum(bool(re.search(p, senha)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]")) < 3:
        erros.append("use ao menos 3 tipos: minúscula, maiúscula, número, símbolo")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in senha.lower():
        erros.append("não use o e-mail na senha")
    if len(nome) >= 4 and nome.split()[0].lower() in senha.lower() and len(nome.split()[0]) >= 4:
        erros.append("não use o seu nome na senha")
    if erros:
        raise ValueError("Senha fraca: " + "; ".join(erros) + ".")


def senha_temporaria() -> str:
    return "Tmp-" + secrets.token_urlsafe(12) + "9!"


# ------------------------------------------------------------------ limite de requisições (memória do processo)

class LimiteRequisicoes:
    def __init__(self):
        self._j: dict[str, deque] = defaultdict(deque)

    def permitir(self, chave: str, maximo: int, janela_seg: int) -> bool:
        agora, fila = time.monotonic(), self._j[chave]
        while fila and agora - fila[0] > janela_seg:
            fila.popleft()
        if len(fila) >= maximo:
            return False
        fila.append(agora)
        return True


# ------------------------------------------------------------------ bloqueio de login

def _chave_email(email: str) -> str:
    return "e:" + _sha(email.strip().lower())[:32]


def _chave_ip(ip: str) -> str:
    return "i:" + _sha(ip or "?")[:32]


def minutos_bloqueado(central, chave: str) -> int:
    r = central.execute("SELECT bloqueado_ate FROM tentativas_login WHERE chave = ?", (chave,)).fetchone()
    if r and r["bloqueado_ate"] > time.time():
        return max(1, int((r["bloqueado_ate"] - time.time()) // 60) + 1)
    return 0


def registrar_falha(central, chave: str, maximo: int) -> None:
    agora = time.time()
    r = central.execute("SELECT * FROM tentativas_login WHERE chave = ?", (chave,)).fetchone()
    if r is None or agora - r["janela_inicio"] > config.BLOQUEIO_LOGIN_SEG:
        falhas, ini = 1, agora
    else:
        falhas, ini = r["falhas"] + 1, r["janela_inicio"]
    bloq = agora + config.BLOQUEIO_LOGIN_SEG if falhas >= maximo else 0
    central.execute("INSERT INTO tentativas_login (chave, falhas, janela_inicio, bloqueado_ate) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(chave) DO UPDATE SET falhas = excluded.falhas, janela_inicio = excluded.janela_inicio, "
                    "bloqueado_ate = excluded.bloqueado_ate", (chave, falhas, ini, bloq))


def limpar_falhas(central, chave: str) -> None:
    central.execute("DELETE FROM tentativas_login WHERE chave = ?", (chave,))


def desbloquear_usuario(central, email: str) -> None:
    limpar_falhas(central, _chave_email(email))


def tentar_login(central, email: str, senha: str, ip: str):
    """Devolve (usuario, mensagem_de_erro). Mensagem genérica; só avisa do bloqueio."""
    ke, ki = _chave_email(email), _chave_ip(ip)
    espera = max(minutos_bloqueado(central, ke), minutos_bloqueado(central, ki))
    if espera:
        registrar_acesso(central, None, None, "login", "bloqueado", ip=ip)
        return None, f"Muitas tentativas. Tente novamente em cerca de {espera} min."
    u = central.execute("SELECT * FROM usuarios WHERE email = ? AND ativo = 1", (email.strip().lower(),)).fetchone()
    ok = conferir_senha(senha, u["senha_hash"] if u else _HASH_FALSO)  # mesmo custo existindo ou não
    if u and ok:
        limpar_falhas(central, ke)
        return u, None
    registrar_falha(central, ke, config.MAX_FALHAS_LOGIN)
    registrar_falha(central, ki, config.MAX_FALHAS_LOGIN_IP)
    registrar_acesso(central, u["id"] if u else None, None, "login", "negado", ip=ip)
    return None, "E-mail ou senha incorretos."


# ------------------------------------------------------------------ sessões

@dataclass
class Sessao:
    token_hash: str
    usuario_id: int
    csrf: str
    mfa_ok: bool
    flash: str | None
    totp_pendente: str | None


def criar_sessao(central, usuario_id: int, mfa_ok: bool, ip: str) -> tuple[str, str]:
    token, agora = secrets.token_urlsafe(32), time.time()
    csrf = secrets.token_urlsafe(24)
    central.execute("INSERT INTO sessoes (token_hash, usuario_id, csrf, criada_em, ultimo_uso, expira_em, mfa_ok, ip) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (_sha(token), usuario_id, csrf, agora, agora, agora + config.SESSAO_MAXIMA_SEG, int(mfa_ok), ip))
    return token, csrf


def obter_sessao(central, token: str | None) -> Sessao | None:
    if not token:
        return None
    h, agora = _sha(token), time.time()
    r = central.execute("SELECT * FROM sessoes WHERE token_hash = ?", (h,)).fetchone()
    if r is None:
        return None
    if agora > r["expira_em"] or agora - r["ultimo_uso"] > config.SESSAO_OCIOSA_SEG:
        central.execute("DELETE FROM sessoes WHERE token_hash = ?", (h,))
        return None
    if agora - r["ultimo_uso"] > 30:
        central.execute("UPDATE sessoes SET ultimo_uso = ? WHERE token_hash = ?", (agora, h))
    return Sessao(h, r["usuario_id"], r["csrf"], bool(r["mfa_ok"]), r["flash"], r["totp_pendente"])


def encerrar_sessao(central, token_hash: str) -> None:
    central.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))


def encerrar_todas(central, usuario_id: int, exceto: str | None = None) -> None:
    central.execute("DELETE FROM sessoes WHERE usuario_id = ? AND token_hash IS NOT ?", (usuario_id, exceto))


def promover_sessao(central, s: Sessao, ip: str) -> str:
    """Troca o token depois de uma mudança de privilégio (2FA): quem roubou o antigo fica de fora."""
    token = secrets.token_urlsafe(32)
    central.execute("UPDATE sessoes SET token_hash = ?, mfa_ok = 1 WHERE token_hash = ?", (_sha(token), s.token_hash))
    return token


def definir_flash(central, token_hash: str, tipo: str, mensagens: list[str]) -> None:
    central.execute("UPDATE sessoes SET flash = ? WHERE token_hash = ?",
                    (json.dumps({"tipo": tipo, "mensagens": mensagens[:60]}, ensure_ascii=False), token_hash))


def tirar_flash(central, s: Sessao) -> dict | None:
    if not s.flash:
        return None
    central.execute("UPDATE sessoes SET flash = NULL WHERE token_hash = ?", (s.token_hash,))
    return json.loads(s.flash)


def limpar_sessoes_vencidas(central) -> None:
    agora = time.time()
    central.execute("DELETE FROM sessoes WHERE expira_em < ? OR ultimo_uso < ?", (agora, agora - config.SESSAO_OCIOSA_SEG))


# ------------------------------------------------------------------ 2FA (TOTP)

def novo_segredo() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(segredo: str, passo: int) -> str:
    chave = base64.b32decode(segredo + "=" * (-len(segredo) % 8))
    h = hmac.new(chave, struct.pack(">Q", passo), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


def passo_atual(agora: float | None = None) -> int:
    return int((agora or time.time()) // 30)


def verificar_totp(segredo: str, codigo: str, ultimo_passo: int, agora: float | None = None) -> int | None:
    """Passo aceito (para gravar) ou None. Aceita ±1 passo e recusa reutilizar um passo já usado."""
    codigo = re.sub(r"\s", "", codigo or "")
    if not re.fullmatch(r"\d{6}", codigo):
        return None
    atual = passo_atual(agora)
    for p in (atual, atual - 1, atual + 1):
        if p > ultimo_passo and hmac.compare_digest(_codigo(segredo, p), codigo):
            return p
    return None


def uri_totp(segredo: str, email: str) -> str:
    return f"otpauth://totp/Conciliador:{email}?secret={segredo}&issuer=Conciliador&digits=6&period=30"


def segredo_do_usuario(u) -> str | None:
    return cripto.recuperar_texto(u["totp_segredo"]) if u["totp_segredo"] else None


def ativar_totp(central, usuario_id: int, segredo: str) -> list[str]:
    central.execute("UPDATE usuarios SET totp_segredo = ?, totp_ativo = 1, totp_ultimo_passo = ? WHERE id = ?",
                    (cripto.proteger_texto(segredo), passo_atual(), usuario_id))
    codigos = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(8)]
    central.execute("DELETE FROM codigos_recuperacao WHERE usuario_id = ?", (usuario_id,))
    central.executemany("INSERT INTO codigos_recuperacao (usuario_id, codigo_hash) VALUES (?, ?)",
                        [(usuario_id, _sha(c)) for c in codigos])
    return codigos


def usar_codigo_recuperacao(central, usuario_id: int, codigo: str) -> bool:
    h = _sha((codigo or "").strip().lower())
    cur = central.execute("UPDATE codigos_recuperacao SET usado_em = datetime('now') WHERE usuario_id = ? "
                          "AND codigo_hash = ? AND usado_em IS NULL", (usuario_id, h))
    return cur.rowcount == 1


def desativar_totp(central, usuario_id: int) -> None:
    central.execute("UPDATE usuarios SET totp_segredo = NULL, totp_ativo = 0, totp_ultimo_passo = 0 WHERE id = ?", (usuario_id,))
    central.execute("DELETE FROM codigos_recuperacao WHERE usuario_id = ?", (usuario_id,))


def exige_2fa(usuario) -> bool:
    return config.EXIGIR_2FA and usuario["papel_global"] != "cliente"


# ------------------------------------------------------------------ cabeçalhos

def cabecalhos() -> dict[str, str]:
    h = {
        "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
                                   "base-uri 'none'; frame-ancestors 'none'",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cache-Control": "no-store",
    }
    if config.COOKIE_SEGURO:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return h
