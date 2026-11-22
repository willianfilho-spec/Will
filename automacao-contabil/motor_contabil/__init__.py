"""Motor de automação de lançamentos contábeis a partir de extratos bancários.

Prova de conceito. Ver README.md para escopo, limitações e próximos passos.
"""

from .banco import BancoDeDados
from .exportador_fortes import ErroDeExportacao, ExportadorFortes
from .modelo import Status, Transacao
from .motor import Motor, ResultadoImportacao
from .plano_contas import PlanoDeContas
from .regras import ConjuntoDeRegras

__all__ = [
    "BancoDeDados",
    "ConjuntoDeRegras",
    "ErroDeExportacao",
    "ExportadorFortes",
    "Motor",
    "PlanoDeContas",
    "ResultadoImportacao",
    "Status",
    "Transacao",
]
