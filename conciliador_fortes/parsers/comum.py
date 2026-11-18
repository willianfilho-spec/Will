"""Utilidades comuns dos leitores de arquivo."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime


class ErroEstrutural(ValueError):
    """Arquivo recusado inteiro. `problemas` lista tudo o que foi encontrado."""

    def __init__(self, problemas: list[str]):
        self.problemas = problemas
        super().__init__("Arquivo recusado:\n- " + "\n- ".join(problemas[:50])
                         + (f"\n- ... e mais {len(problemas) - 50}" if len(problemas) > 50 else ""))


def decodificar(bruto: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1")


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento, espaços simples. Base para regras e comparação."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().upper()


def sanitizar_texto(texto) -> str:
    """Remove controles e neutraliza início de fórmula (=, +, -, @) vindo de planilha."""
    if texto is None:
        return ""
    t = str(texto)
    t = "".join(c for c in t if c in "\t" or unicodedata.category(c)[0] != "C")
    t = re.sub(r"\s+", " ", t).strip()
    while t[:1] in ("=", "+", "@") or (t[:1] == "-" and not re.match(r"-\s*\d", t)):
        t = t[1:].strip()
    return t


FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%Y%m%d")


def para_data(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    t = str(valor or "").strip()
    if " " in t:
        t = t.split(" ")[0]
    for fmt in FORMATOS_DATA:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {valor!r}")
