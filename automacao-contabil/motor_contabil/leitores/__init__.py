"""Leitores de extrato. `ler_extrato` escolhe pelo tipo do arquivo."""

from __future__ import annotations

from pathlib import Path

from ..modelo import Transacao
from .csv_extrato import ler_csv
from .itau_pdf import ler_itau_pdf, ler_itau_pdf_completo
from .ofx import ler_ofx
from .xlsx_extrato import ler_xlsx


def ler_extrato(caminho: str | Path, conta_bancaria: str | None = None) -> list[Transacao]:
    sufixo = Path(caminho).suffix.lower()
    if sufixo in {".ofx", ".ofc"}:
        return ler_ofx(caminho, conta_bancaria)
    if sufixo in {".csv", ".txt"}:
        if not conta_bancaria:
            raise ValueError("Para CSV, informe a conta bancária (o arquivo não a contém).")
        return ler_csv(caminho, conta_bancaria)
    if sufixo == ".xlsx":
        if not conta_bancaria:
            raise ValueError("Para planilha Excel, informe a conta bancária (o arquivo não a contém).")
        return ler_xlsx(caminho, conta_bancaria)
    if sufixo == ".pdf":
        if not conta_bancaria:
            raise ValueError("Para extrato em PDF, informe a conta bancária.")
        return ler_itau_pdf(caminho, conta_bancaria)
    raise ValueError(f"Formato {sufixo!r} ainda não suportado. Use OFX, CSV, XLSX ou PDF do Itaú.")


__all__ = ["ler_extrato", "ler_ofx", "ler_csv", "ler_xlsx", "ler_itau_pdf", "ler_itau_pdf_completo"]
