"""Estruturas de dados do motor.

Valores monetários são sempre Decimal (nunca float): um centavo perdido por
arredondamento binário é exatamente o tipo de erro que o motor precisa evitar.
Convenção de sinal: valor > 0 é entrada no banco; valor < 0 é saída.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class Status(str, Enum):
    LIBERADO = "liberado"          # pronto para exportar
    PENDENTE = "pendente"          # precisa de revisão humana
    BLOQUEADO = "bloqueado"        # erro que impede a exportação
    DESCARTADO = "descartado"      # revisor confirmou que é duplicidade/indevido
    EXPORTADO = "exportado"        # já saiu em um arquivo de importação


@dataclass(frozen=True)
class Transacao:
    """Uma linha do extrato, como veio do banco (sem interpretação contábil)."""

    conta_bancaria: str
    data: date
    valor: Decimal
    historico: str
    documento: str | None = None
    fitid: str | None = None
    origem: str = ""
    linha: int = 0
    favorecido: str | None = None
    # Avisos do leitor sobre a qualidade da linha (ex.: texto truncado na
    # extração do PDF). Cada aviso manda o lançamento para revisão.
    alertas: tuple[str, ...] = ()

    @property
    def sentido(self) -> str:
        return "entrada" if self.valor > 0 else "saida"


@dataclass
class Classificacao:
    conta_contrapartida: str | None
    historico_padrao: str | None
    fonte: str  # "regra:<id>", "ia", "manual" ou "nenhuma"
    observacao: str = ""


@dataclass
class Lancamento:
    chave: str
    transacao: Transacao
    conta_debito: str | None
    conta_credito: str | None
    historico: str
    status: Status
    motivos: list[str] = field(default_factory=list)
    fonte: str = "nenhuma"
