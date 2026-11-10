"""Etapa 3: gravação dos arquivos de saída."""

import csv
from pathlib import Path

from .modelos import STATUS_CLASSIFICADO, Lancamento

CABECALHO = [
    "data", "conta_debito", "conta_credito", "valor", "historico",
    "documento", "origem", "status", "observacao", "linha_extrato",
]


def _formatar_valor(valor) -> str:
    return f"{valor:.2f}".replace(".", ",")


def _gravar(caminho: Path, lancamentos: list[Lancamento]) -> None:
    # utf-8-sig e ponto e vírgula: o arquivo abre direto no Excel em português.
    with open(caminho, "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(CABECALHO)
        for l in lancamentos:
            escritor.writerow([
                l.data.strftime("%d/%m/%Y"), l.conta_debito, l.conta_credito,
                _formatar_valor(l.valor), l.historico, l.documento,
                l.origem, l.status, l.observacao, l.linha_extrato,
            ])


def exportar(lancamentos: list[Lancamento], pasta_saida) -> tuple[Path, Path]:
    """Grava todos os lançamentos e, à parte, só os que exigem revisão."""
    pasta = Path(pasta_saida)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo_todos = pasta / "lancamentos.csv"
    arquivo_revisao = pasta / "revisao.csv"
    _gravar(arquivo_todos, lancamentos)
    _gravar(arquivo_revisao, [l for l in lancamentos if l.status != STATUS_CLASSIFICADO])
    return arquivo_todos, arquivo_revisao
