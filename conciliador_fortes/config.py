"""Configuração local do Conciliador Fortes.

Tudo roda na máquina do escritório (Etapa A). Os dados ficam em DATA_DIR,
fora do repositório: nunca versione a pasta data/.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CONCILIADOR_DATA_DIR", BASE_DIR / "data")).resolve()
BACKUP_DIR = Path(os.environ.get("CONCILIADOR_BACKUP_DIR", DATA_DIR / "backups")).resolve()

# Sugestão por IA fica desligada. Mesmo ligada, nunca aprova nada: só propõe.
ENABLE_AI = False

# R$ 10.000,00: valor igual ou acima exige segunda confirmação (padrão da empresa).
LIMITE_REVISAO_PADRAO_CENTAVOS = 1_000_000

# Leiaute de importação do Fortes conferido em arquivos reais (ver exporters/fortes_exporter.py).
# O limite do histórico não está documentado; 118 veio do exportador anterior. Confirme no Fortes.
LIMITE_HISTORICO = 118

# Semelhança mínima de histórico (0 a 1) para alertar possível duplicidade entre arquivos.
LIMIAR_SEMELHANCA = 0.85

# Janela, em dias, para cruzar um movimento do extrato com a planilha de despesas.
JANELA_PLANILHA_DIAS = 3

# SQLite: espera até 5 s por uma trava de escrita antes de falhar.
BUSY_TIMEOUT_MS = 5000

PAPEIS_GLOBAIS = ("cliente", "equipe", "revisor", "aprovador", "admin")
PAPEIS_EMPRESA = ("cliente", "operador", "revisor", "aprovador")
