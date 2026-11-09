"""Plano de contas parametrizável por escritório/empresa.

Arquivo CSV com cabeçalho: codigo;descricao;tipo[;codigo_exportacao]
  - tipo: A (analítica, aceita lançamento) ou S (sintética, só agrupa).
  - codigo_exportacao (opcional): o código que o sistema contábil de destino
    espera (ex.: código reduzido). Se vazio, exporta o próprio `codigo`.

Não se presume que o código de um escritório vale para outro: cada empresa
tem o seu arquivo.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Conta:
    codigo: str
    descricao: str
    analitica: bool
    codigo_exportacao: str


class PlanoDeContas:
    def __init__(self, contas: list[Conta]):
        self._contas = {c.codigo: c for c in contas}

    @classmethod
    def carregar(cls, caminho: str | Path) -> "PlanoDeContas":
        texto = Path(caminho).read_text(encoding="utf-8-sig")
        delimitador = ";" if texto.count(";") >= texto.count(",") else ","
        contas = []
        for linha in csv.DictReader(texto.splitlines(), delimiter=delimitador):
            codigo = (linha.get("codigo") or "").strip()
            if not codigo:
                continue
            contas.append(
                Conta(
                    codigo=codigo,
                    descricao=(linha.get("descricao") or "").strip(),
                    analitica=(linha.get("tipo") or "A").strip().upper() == "A",
                    codigo_exportacao=(linha.get("codigo_exportacao") or "").strip()
                    or codigo,
                )
            )
        return cls(contas)

    def get(self, codigo: str | None) -> Conta | None:
        return self._contas.get(codigo or "")

    def analiticas(self) -> list[Conta]:
        return [c for c in self._contas.values() if c.analitica]

    def problema(self, codigo: str | None) -> str | None:
        """Motivo pelo qual a conta não pode receber lançamento, ou None."""
        if not codigo:
            return "conta não definida"
        conta = self.get(codigo)
        if conta is None:
            return f"conta {codigo} não existe no plano de contas"
        if not conta.analitica:
            return f"conta {codigo} é sintética e não aceita lançamento"
        return None
