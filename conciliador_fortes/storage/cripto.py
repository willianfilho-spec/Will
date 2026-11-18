"""Criptografia em repouso dos arquivos enviados e gerados (AES-256-GCM).

- Chave mestra: variável CONCILIADOR_CHAVE (32 bytes em base64) ou, se não existir,
  um arquivo `chave.key` (0600) criado ao lado dos dados. O arquivo ao lado dos dados é
  conveniente e fraco: quem copiar a pasta leva a chave junto. Em produção use a variável
  de ambiente (ou um cofre) e guarde uma cópia da chave FORA do backup dos dados.
- Cada empresa usa uma chave derivada (HKDF) do seu identificador: o arquivo de uma
  empresa não abre com a chave de outra.
- Formato do arquivo: MAGIC + nonce(12) + texto cifrado. O SHA-256 gravado no banco é sempre do
  conteúdo em claro.
- NÃO cifra o banco SQLite. Para o banco, use criptografia de disco (BitLocker/LUKS).
- Perder a chave significa perder os arquivos. Faça cópia da chave.
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import config

MAGIC = b"\x00CFENC1\x00"


class ErroCripto(RuntimeError):
    pass


def ativa() -> bool:
    return bool(os.environ.get("CONCILIADOR_CHAVE")) or os.environ.get("CONCILIADOR_CRIPTO") == "1"


def _arquivo_chave() -> Path:
    return config.DATA_DIR / "chave.key"


def chave_mestra() -> bytes:
    env = os.environ.get("CONCILIADOR_CHAVE")
    if env:
        try:
            k = base64.b64decode(env, validate=True)
        except ValueError as exc:
            raise ErroCripto("CONCILIADOR_CHAVE não é base64 válido") from exc
        if len(k) != 32:
            raise ErroCripto("CONCILIADOR_CHAVE deve ter 32 bytes (gere com scripts/gerar_chave.py)")
        return k
    f = _arquivo_chave()
    if f.exists():
        return base64.b64decode(f.read_text().strip())
    f.parent.mkdir(parents=True, exist_ok=True)
    k = secrets.token_bytes(32)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as h:
        h.write(base64.b64encode(k).decode())
    return k


def _chave(slug: str, finalidade: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"conciliador|{finalidade}|{slug}".encode()).derive(chave_mestra())


def proteger(slug: str, bruto: bytes) -> bytes:
    if not ativa():
        return bruto
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(_chave(slug, "arquivo")).encrypt(nonce, bruto, slug.encode())


def recuperar(slug: str, guardado: bytes) -> bytes:
    if not guardado.startswith(MAGIC):
        return guardado  # arquivo gravado antes de a criptografia ser ligada
    try:
        nonce, corpo = guardado[len(MAGIC):len(MAGIC) + 12], guardado[len(MAGIC) + 12:]
        return AESGCM(_chave(slug, "arquivo")).decrypt(nonce, corpo, slug.encode())
    except Exception as exc:
        raise ErroCripto("não foi possível abrir o arquivo: chave errada, arquivo de outra empresa ou adulterado") from exc


def proteger_texto(texto: str, finalidade: str = "campo") -> str:
    """Para segredos curtos no banco (ex.: semente do 2FA)."""
    if not ativa():
        return "claro:" + texto
    nonce = secrets.token_bytes(12)
    return "aes:" + base64.b64encode(nonce + AESGCM(_chave("global", finalidade)).encrypt(nonce, texto.encode(), None)).decode()


def recuperar_texto(guardado: str, finalidade: str = "campo") -> str:
    if guardado.startswith("claro:"):
        return guardado[6:]
    if not guardado.startswith("aes:"):
        raise ErroCripto("formato de segredo desconhecido")
    bruto = base64.b64decode(guardado[4:])
    try:
        return AESGCM(_chave("global", finalidade)).decrypt(bruto[:12], bruto[12:], None).decode()
    except Exception as exc:
        raise ErroCripto("não foi possível abrir o segredo (chave errada?)") from exc
