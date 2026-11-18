"""Leitor de extrato OFX (SGML 1.x e XML 2.x) sem dependências externas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from domain.money import ValorInvalido, para_centavos
from parsers.comum import ErroEstrutural, decodificar, sanitizar_texto


@dataclass
class ExtratoOFX:
    banco: str | None
    agencia: str | None
    conta: str | None
    inicio: str | None
    fim: str | None
    saldo_final_centavos: int | None
    saldo_data: str | None
    movimentos: list[dict] = field(default_factory=list)


def _campo(bloco: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>([^<\r\n]*)", bloco, flags=re.I)
    return m.group(1).strip() if m else None


def _data_ofx(valor: str | None) -> str | None:
    if not valor:
        return None
    m = re.match(r"(\d{4})(\d{2})(\d{2})", valor.strip())
    if not m:
        raise ValueError(f"data OFX inválida: {valor!r}")
    a, me, d = m.groups()
    if not (1 <= int(me) <= 12 and 1 <= int(d) <= 31):
        raise ValueError(f"data OFX inválida: {valor!r}")
    return f"{a}-{me}-{d}"


def ler_ofx(bruto: bytes) -> ExtratoOFX:
    texto = decodificar(bruto)
    if "<OFX>" not in texto.upper():
        raise ErroEstrutural(["não é um arquivo OFX (marca <OFX> ausente)"])
    blocos = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, flags=re.I | re.S)
    if not blocos:
        # SGML sem fechamento de STMTTRN: corta pelo próximo <STMTTRN> ou </BANKTRANLIST>
        partes = re.split(r"<STMTTRN>", texto, flags=re.I)[1:]
        blocos = [re.split(r"</BANKTRANLIST>", p, flags=re.I)[0] for p in partes]
    problemas: list[str] = []
    movimentos: list[dict] = []
    for i, b in enumerate(blocos, start=1):
        try:
            data = _data_ofx(_campo(b, "DTPOSTED"))
            if data is None:
                raise ValueError("DTPOSTED ausente")
            valor_txt = _campo(b, "TRNAMT")
            if valor_txt is None:
                raise ValueError("TRNAMT ausente")
            valor = para_centavos(valor_txt)
            if valor == 0:
                raise ValueError("valor zero")
        except (ValueError, ValorInvalido) as exc:
            problemas.append(f"transação {i}: {exc}")
            continue
        nome = sanitizar_texto(_campo(b, "NAME"))
        memo = sanitizar_texto(_campo(b, "MEMO"))
        partes: list[str] = []
        for x in (memo, nome):
            if x and not any(x in p for p in partes):
                partes.append(x)
        historico = " ".join(partes) or (_campo(b, "TRNTYPE") or "SEM HISTORICO")
        movimentos.append({
            "linha": i,
            "data": data,
            "valor_centavos": valor,
            "historico": historico,
            "documento": sanitizar_texto(_campo(b, "CHECKNUM") or _campo(b, "REFNUM")) or None,
            "fitid": sanitizar_texto(_campo(b, "FITID")) or None,
        })
    if problemas:
        raise ErroEstrutural(problemas)
    if not movimentos:
        raise ErroEstrutural(["nenhuma transação (<STMTTRN>) encontrada"])
    saldo = None
    m = re.search(r"<LEDGERBAL>(.*?)(</LEDGERBAL>|<AVAILBAL>|$)", texto, flags=re.I | re.S)
    if m and _campo(m.group(1), "BALAMT"):
        try:
            saldo = para_centavos(_campo(m.group(1), "BALAMT"))
        except ValorInvalido:
            saldo = None
    return ExtratoOFX(
        banco=_campo(texto, "BANKID"),
        agencia=_campo(texto, "BRANCHID"),
        conta=_campo(texto, "ACCTID"),
        inicio=_data_ofx(_campo(texto, "DTSTART")),
        fim=_data_ofx(_campo(texto, "DTEND")),
        saldo_final_centavos=saldo,
        saldo_data=_data_ofx(_campo(m.group(1), "DTASOF")) if m else None,
        movimentos=movimentos,
    )
