"""Leitor de OFX 1.x (SGML, sem tags de fechamento) e 2.x (XML).

Os bancos brasileiros variam bastante no OFX que geram. Este leitor é
tolerante de propósito: lê cada <STMTTRN> por expressão regular em vez de
exigir um documento bem formado.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ..modelo import Transacao
from ..texto import para_decimal


def _decodificar(conteudo: bytes) -> str:
    cabecalho = conteudo[:500].decode("ascii", errors="ignore").upper()
    candidatos = ["utf-8"]
    if "1252" in cabecalho or "ISO-8859-1" in cabecalho or "USASCII" in cabecalho:
        candidatos = ["cp1252", "utf-8"]
    for codificacao in candidatos + ["cp1252"]:
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1")


def _campo(bloco: str, tag: str) -> str | None:
    # Em SGML o valor vai até o próximo '<' ou fim de linha.
    m = re.search(rf"<{tag}>([^<\r\n]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m and m.group(1).strip() else None


def _data(bruto: str) -> date:
    digitos = re.match(r"(\d{4})(\d{2})(\d{2})", bruto)
    if not digitos:
        raise ValueError(f"data OFX inválida: {bruto!r}")
    a, m, d = (int(x) for x in digitos.groups())
    return date(a, m, d)


def identificar_conta(texto: str) -> str | None:
    banco = _campo(texto, "BANKID")
    agencia = _campo(texto, "BRANCHID")
    conta = _campo(texto, "ACCTID")
    if not conta:
        return None
    return "-".join(p for p in (banco, agencia, conta) if p)


def ler_ofx(caminho: str | Path, conta_bancaria: str | None = None) -> list[Transacao]:
    caminho = Path(caminho)
    texto = _decodificar(caminho.read_bytes())
    conta = conta_bancaria or identificar_conta(texto)
    if not conta:
        raise ValueError(
            "Conta bancária não identificada no OFX. Informe-a explicitamente."
        )

    blocos = re.findall(
        r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    transacoes: list[Transacao] = []
    for posicao, bloco in enumerate(blocos, start=1):
        valor_bruto = _campo(bloco, "TRNAMT")
        data_bruta = _campo(bloco, "DTPOSTED")
        if valor_bruto is None or data_bruta is None:
            raise ValueError(f"{caminho.name}: transação {posicao} sem valor ou data")
        historico = " ".join(
            p for p in (_campo(bloco, "NAME"), _campo(bloco, "MEMO")) if p
        )
        transacoes.append(
            Transacao(
                conta_bancaria=conta,
                data=_data(data_bruta),
                valor=para_decimal(valor_bruto),
                historico=historico or (_campo(bloco, "TRNTYPE") or ""),
                documento=_campo(bloco, "CHECKNUM") or _campo(bloco, "REFNUM"),
                fitid=_campo(bloco, "FITID"),
                origem=caminho.name,
                linha=posicao,
            )
        )
    return transacoes
