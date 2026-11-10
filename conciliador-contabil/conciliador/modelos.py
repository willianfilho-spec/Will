"""Estruturas de dados que circulam entre as etapas do programa."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# Origem da classificação de um lançamento.
ORIGEM_REGRA = "REGRA"
ORIGEM_IA = "IA"
ORIGEM_PENDENTE = "PENDENTE"
ORIGEM_MANUAL = "MANUAL"

# Situação do lançamento para quem vai revisar.
STATUS_CLASSIFICADO = "CLASSIFICADO"  # regra objetiva, sem ressalvas
STATUS_REVISAR = "REVISAR"            # tem conta sugerida, mas precisa de conferência
STATUS_PENDENTE = "PENDENTE"          # ficou na conta transitória
STATUS_APROVADO = "APROVADO"          # conferido por uma pessoa na planilha de revisão

STATUS_LIBERADOS = (STATUS_CLASSIFICADO, STATUS_APROVADO)


@dataclass
class Transacao:
    """Uma linha do extrato. Valor positivo = entrada; negativo = saída."""

    linha: int
    data: date
    descricao: str
    valor: Decimal
    documento: str = ""


@dataclass
class Extrato:
    """Resultado da leitura: os movimentos e os saldos informados no arquivo."""

    transacoes: list[Transacao] = field(default_factory=list)
    saldo_inicial: Decimal | None = None
    saldo_final: Decimal | None = None
    linhas_saldo: int = 0


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
    descricao_extrato: str = ""
    fornecedor: str = ""
    regra: str = ""
