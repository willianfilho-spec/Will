"""Exportação para o sistema contábil.

ATENÇÃO: o leiaute abaixo é PROVISÓRIO e genérico. O leiaute definitivo
depende do sistema contábil usado pelo escritório (Domínio, Alterdata,
Fortes, SCI etc.), que ainda não foi definido. Não se deve presumir que este
arquivo é aceito por nenhum deles. Quando o sistema for definido, cria-se uma
nova classe com o mesmo método `escrever`, a partir da documentação oficial
de importação daquele sistema.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from .plano_contas import PlanoDeContas
from .texto import formatar_valor

COLUNAS = ["data", "conta_debito", "conta_credito", "valor", "historico", "documento", "origem"]


class ExportadorCSVGenerico:
    def __init__(self, plano: PlanoDeContas, limite_historico: int = 200):
        self.plano = plano
        self.limite_historico = limite_historico

    def _codigo(self, codigo: str) -> str:
        conta = self.plano.get(codigo)
        return conta.codigo_exportacao if conta else codigo

    def escrever(self, lancamentos: list[dict], destino: str | Path) -> None:
        with open(destino, "w", newline="", encoding="utf-8") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(COLUNAS)
            for item in lancamentos:
                escritor.writerow([
                    date.fromisoformat(item["data"]).strftime("%d/%m/%Y"),
                    self._codigo(item["conta_debito"]),
                    self._codigo(item["conta_credito"]),
                    formatar_valor(Decimal(item["valor"])),
                    item["historico"][: self.limite_historico],
                    item.get("documento") or "",
                    # rastreabilidade: arquivo de origem e linha do extrato
                    f"{item['origem']}#{item['linha']}",
                ])
