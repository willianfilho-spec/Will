"""Identificação de quem usa o sistema, para a trilha de auditoria e os relatórios.

Dois modos, definidos num arquivo de configuração (``acesso.json``) cujo
caminho vem da variável ``MOTOR_CONTABIL_ACESSO``:

- ``local`` (padrão, também sem arquivo): o sistema só é aberto no próprio
  computador e o nome do responsável é digitado. Não há autenticação.
- ``cloudflare``: o sistema é publicado por um túnel da Cloudflare e o
  Cloudflare Access exige login com a conta Google antes de deixar passar.
  A Cloudflare envia em cada acesso um token assinado
  (cabeçalho ``Cf-Access-Jwt-Assertion``). O sistema confere a assinatura com
  as chaves públicas da equipe, o público (AUD) da aplicação e a validade,
  e só então aceita o e-mail do token. O e-mail também precisa estar na
  lista de autorizados deste arquivo (segunda barreira, além da política
  configurada na Cloudflare).

No modo ``cloudflare``, quem abre pelo próprio computador do escritório
(``localhost``) continua entrando sem login, com nome digitado e marcado como
acesso local: o servidor só aceita conexões da própria máquina, então esse
caminho não fica exposto. Acesso sem token vindo de outro endereço é recusado.

Exemplo de ``acesso.json``::

    {
      "modo": "cloudflare",
      "dominio_equipe": "equilibra.cloudflareaccess.com",
      "aud": "<Application Audience (AUD) Tag copiado do painel>",
      "autorizados": {
        "daiane@equilibracontabil.com.br": "Daiane Letícia Freire Azevedo",
        "luciana@equilibracontabil.com.br": "Luciana Ribeiro"
      }
    }

A validação do token requer o pacote ``PyJWT`` com ``cryptography``
(importados só no modo ``cloudflare``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

CABECALHO_TOKEN = "cf-access-jwt-assertion"
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "[::1]", "::1"}


class AcessoNegado(Exception):
    """Acesso recusado; a mensagem diz o que fazer."""


@dataclass(frozen=True)
class ConfigAcesso:
    modo: str = "local"
    dominio_equipe: str = ""
    aud: str = ""
    autorizados: dict[str, str] = field(default_factory=dict)

    @property
    def remoto(self) -> bool:
        return self.modo == "cloudflare"


@dataclass(frozen=True)
class Identidade:
    nome: str
    email: str | None
    autenticado: bool

    @property
    def para_auditoria(self) -> str:
        """Texto gravado na trilha de auditoria e nos relatórios."""
        if self.autenticado and self.email:
            return f"{self.nome} <{self.email}>"
        return f"{self.nome} (acesso local, sem login)"


def carregar_config(caminho: str | Path | None) -> ConfigAcesso:
    if not caminho or not Path(caminho).exists():
        return ConfigAcesso()
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ValueError(f"{caminho}: arquivo de acesso ilegível ({erro}). "
                         "Rode 5_CONFIGURAR_ACESSO_REMOTO.bat de novo.") from erro
    modo = dados.get("modo", "local")
    if modo not in ("local", "cloudflare"):
        raise ValueError(f"{caminho}: modo '{modo}' desconhecido; use 'local' ou 'cloudflare'.")
    autorizados = {str(k).strip().lower(): str(v).strip() for k, v in dados.get("autorizados", {}).items()}
    cfg = ConfigAcesso(modo, str(dados.get("dominio_equipe", "")).strip().lower(),
                       str(dados.get("aud", "")).strip(), autorizados)
    if cfg.remoto:
        faltando = [n for n, v in (("dominio_equipe", cfg.dominio_equipe), ("aud", cfg.aud)) if not v]
        if faltando:
            raise ValueError(f"{caminho}: faltam {', '.join(faltando)} para o modo cloudflare.")
        if not re.fullmatch(r"[a-z0-9-]+\.cloudflareaccess\.com", cfg.dominio_equipe):
            raise ValueError(f"{caminho}: dominio_equipe deve ser algo como "
                             "'equipe.cloudflareaccess.com'.")
        if not autorizados:
            raise ValueError(f"{caminho}: inclua ao menos um e-mail em 'autorizados'.")
    return cfg


def _cabecalho(headers: Mapping[str, str], nome: str) -> str | None:
    for chave, valor in headers.items():
        if chave.lower() == nome:
            return valor
    return None


def _host_local(headers: Mapping[str, str]) -> bool:
    host = (_cabecalho(headers, "host") or "").strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in HOSTS_LOCAIS


_clientes_jwk: dict[str, object] = {}


def _chave_da_cloudflare(token: str, cfg: ConfigAcesso):
    import jwt

    url = f"https://{cfg.dominio_equipe}/cdn-cgi/access/certs"
    cliente = _clientes_jwk.get(url)
    if cliente is None:
        cliente = _clientes_jwk[url] = jwt.PyJWKClient(url, cache_keys=True)
    return cliente.get_signing_key_from_jwt(token).key


def validar_token(token: str, cfg: ConfigAcesso,
                  obter_chave: Callable[[str, ConfigAcesso], object] | None = None) -> str:
    """Confere assinatura, público, emissor e validade. Devolve o e-mail em minúsculas."""
    import jwt

    obter_chave = obter_chave or _chave_da_cloudflare
    try:
        chave = obter_chave(token, cfg)
        dados = jwt.decode(
            token, chave, algorithms=["RS256"], audience=cfg.aud,
            issuer=f"https://{cfg.dominio_equipe}", options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as erro:
        raise AcessoNegado("Sua sessão expirou. Recarregue a página e entre de novo com a conta Google.") from erro
    except Exception as erro:  # assinatura, público, emissor, chave indisponível
        raise AcessoNegado("Não foi possível confirmar o login. Recarregue a página; se persistir, "
                           f"avise o responsável pelo sistema ({type(erro).__name__}).") from erro
    email = str(dados.get("email", "")).strip().lower()
    if not email:
        raise AcessoNegado("O login não informou o e-mail. Avise o responsável pelo sistema.")
    return email


def identificar(headers: Mapping[str, str], cfg: ConfigAcesso,
                obter_chave: Callable[[str, ConfigAcesso], object] | None = None) -> Identidade | None:
    """Quem está usando o sistema.

    Devolve ``None`` quando o acesso é local e o nome deve ser digitado.
    Levanta ``AcessoNegado`` quando o acesso remoto não pode ser confirmado.
    """
    if not cfg.remoto:
        return None
    token = _cabecalho(headers, CABECALHO_TOKEN)
    if not token:
        if _host_local(headers):
            return None
        raise AcessoNegado("Acesso sem login. Entre pelo endereço do sistema com a conta Google "
                           "autorizada.")
    email = validar_token(token, cfg, obter_chave)
    if email not in cfg.autorizados:
        raise AcessoNegado(f"A conta {email} não está autorizada a usar o sistema. Peça ao "
                           "responsável para incluí-la.")
    return Identidade(cfg.autorizados[email] or email, email, True)


# ------------------------------------------------------------------ configuração pelo terminal

def _perguntar(texto: str, entrada=input) -> str:
    return entrada(texto).strip()


def configurar(caminho: str | Path, entrada=input, saida=print) -> ConfigAcesso:
    """Pergunta os dados do Cloudflare Access e grava o arquivo de acesso.

    Mantém os e-mails já autorizados se o arquivo existir.
    """
    caminho = Path(caminho)
    try:
        atual = carregar_config(caminho)
    except ValueError:
        atual = ConfigAcesso()
    saida("Dados do painel da Cloudflare (Zero Trust > Access > Applications > sua aplicação).")
    equipe = _perguntar(f"Domínio da equipe [{atual.dominio_equipe or 'ex.: equilibra.cloudflareaccess.com'}]: ",
                        entrada) or atual.dominio_equipe
    equipe = equipe.lower().removeprefix("https://").strip("/")
    aud = _perguntar(f"Application Audience (AUD) Tag [{'mantém o atual' if atual.aud else 'obrigatório'}]: ",
                     entrada) or atual.aud
    autorizados = dict(atual.autorizados)
    if autorizados:
        saida("Já autorizados: " + ", ".join(f"{n} <{e}>" for e, n in autorizados.items()))
    saida("Inclua os e-mails autorizados (Enter vazio para terminar). "
          "Para remover alguém, digite -email.")
    while True:
        email = _perguntar("E-mail: ", entrada).lower()
        if not email:
            break
        if email.startswith("-"):
            autorizados.pop(email[1:], None)
            continue
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            saida("E-mail inválido; tente de novo.")
            continue
        autorizados[email] = _perguntar("Nome completo (aparece na auditoria): ", entrada) or email
    dados = {"modo": "cloudflare", "dominio_equipe": equipe, "aud": aud, "autorizados": autorizados}
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        cfg = carregar_config(temporario)
    except ValueError as erro:
        temporario.unlink(missing_ok=True)
        raise ValueError(str(erro).replace(str(temporario), str(caminho))) from erro
    temporario.replace(caminho)
    saida(f"Gravado em {caminho}: {len(cfg.autorizados)} e-mail(s) autorizado(s).")
    return cfg


def verificar(caminho: str | Path, saida=print) -> bool:
    """Confere o arquivo e se as chaves públicas da equipe podem ser obtidas."""
    cfg = carregar_config(caminho)
    if not cfg.remoto:
        saida("Modo local: o sistema só abre neste computador, sem login.")
        return True
    import jwt

    try:
        jwt.PyJWKClient(f"https://{cfg.dominio_equipe}/cdn-cgi/access/certs").get_signing_keys()
    except Exception as erro:
        saida(f"ERRO: não consegui obter as chaves de {cfg.dominio_equipe} ({erro}). "
              "Confira o domínio da equipe e a internet.")
        return False
    saida(f"OK: chaves de {cfg.dominio_equipe} obtidas; {len(cfg.autorizados)} e-mail(s) autorizado(s).")
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Configura o acesso remoto com login Google (Cloudflare Access).")
    p.add_argument("acao", choices=["configurar", "verificar"])
    p.add_argument("arquivo", help="caminho do acesso.json")
    args = p.parse_args(argv)
    try:
        if args.acao == "configurar":
            configurar(args.arquivo)
            return 0 if verificar(args.arquivo) else 1
        return 0 if verificar(args.arquivo) else 1
    except ValueError as erro:
        print(f"ERRO: {erro}")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
