"""Estruturas de dados que circulam entre as etapas do programa."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Origem da classificação de um lançamento.
ORIGEM_REGRA = "REGRA"
ORIGEM_IA = "IA"
ORIGEM_PENDENTE = "PENDENTE"

# Situação do lançamento para quem vai revisar.
STATUS_CLASSIFICADO = "CLASSIFICADO"  # regra objetiva, sem ressalvas
STATUS_REVISAR = "REVISAR"            # tem conta sugerida, mas precisa de conferência
STATUS_PENDENTE = "PENDENTE"          # ficou na conta transitória


@dataclass
class Transacao:
    """Uma linha do extrato. Valor positivo = entrada; negativo = saída."""

    linha: int
    data: date
    descricao: str
    valor: Decimal
    documento: str = ""


@dataclass
class Lancamento:
    """Um lançamento contábil em partidas dobradas (um débito, um crédito)."""

    data: date
    conta_debito: str
    conta_credito: str
    valor: Decimal  # sempre positivo
    historico: str
    documento: str
    origem: str
    status: str
    observacao: str = ""
    linha_extrato: int = 0
