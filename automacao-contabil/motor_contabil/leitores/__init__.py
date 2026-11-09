"""Leitores de extrato. `ler_extrato` escolhe pelo tipo do arquivo."""

from __future__ import annotations

from pathlib import Path

from ..modelo import Transacao
from .csv_extrato import ler_csv
from .ofx import ler_ofx
from .planilha_despesas import ler_planilha_despesas


def ler_extrato(caminho: str | Path, conta_bancaria: str | None = None) -> list[Transacao]:
    sufixo = Path(caminho).suffix.lower()
    if sufixo in {".ofx", ".ofc"}:
        return ler_ofx(caminho, conta_bancaria)
    if sufixo in {".csv", ".txt"}:
        if not conta_bancaria:
            raise ValueError("Para CSV, informe a conta bancária (o arquivo não a contém).")
        return ler_csv(caminho, conta_bancaria)
    if sufixo in {".xlsx", ".xlsm"}:
        if not conta_bancaria:
            raise ValueError("Para planilha, informe a conta bancária (a coluna CAIXA/BANCO vem vazia).")
        return ler_planilha_despesas(caminho, conta_bancaria)
    raise ValueError(f"Formato {sufixo!r} ainda não suportado. Use OFX, CSV ou XLSX.")


__all__ = ["ler_extrato", "ler_ofx", "ler_csv", "ler_planilha_despesas"]
