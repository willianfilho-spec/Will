"""Leitor de Razão/lançamentos do Fortes para a conferência de saldo.

Há dois caminhos, porque ainda não temos um arquivo real de Razão exportado:

1. `ler_lancamentos_fortes`: o próprio leiaute de importação
   (data;debito;credito;valor;historico;;;;). Serve para carregar lotes já
   importados e conferidos. Leiaute confirmado em arquivos reais.
2. `ler_razao_tabular`: CSV/XLSX genérico com colunas mapeadas
   (data, conta, débito, crédito, histórico). LEIAUTE A CONFIRMAR com um Razão
   real do Fortes antes de usar no fechamento.
"""

from __future__ import annotations

import csv
import io

from domain.money import ValorInvalido, para_centavos
from parsers.comum import ErroEstrutural, decodificar, para_data, sanitizar_texto
from parsers.tabular_parser import ler_tabela


def ler_lancamentos_fortes(bruto: bytes) -> list[dict]:
    """Cada linha vira duas partidas: débito na conta D e crédito na conta C."""
    texto = decodificar(bruto)
    problemas, partidas = [], []
    for n, campos in enumerate(csv.reader(io.StringIO(texto, newline=""), delimiter=";"), start=1):
        if not campos or not "".join(campos).strip():
            continue
        if len(campos) < 5:
            problemas.append(f"linha {n}: esperados 9 campos (data;debito;credito;valor;historico;;;;)")
            continue
        try:
            d = para_data(campos[0]).isoformat()
            v = para_centavos(campos[3])
            if v <= 0:
                raise ValorInvalido("valor deve ser positivo")
        except (ValueError, ValorInvalido) as exc:
            problemas.append(f"linha {n}: {exc}")
            continue
        deb, cred, hist = campos[1].strip(), campos[2].strip(), sanitizar_texto(campos[4])
        if not deb or not cred:
            problemas.append(f"linha {n}: conta de débito ou crédito vazia")
            continue
        partidas.append({"data": d, "conta": deb, "debito_centavos": v, "credito_centavos": 0, "historico": hist})
        partidas.append({"data": d, "conta": cred, "debito_centavos": 0, "credito_centavos": v, "historico": hist})
    if problemas:
        raise ErroEstrutural(problemas)
    if not partidas:
        raise ErroEstrutural(["nenhum lançamento encontrado"])
    return partidas


def ler_razao_tabular(bruto: bytes, nome_arquivo: str, col_data: str, col_conta: str,
                      col_debito: str, col_credito: str, col_historico: str | None = None) -> list[dict]:
    _, linhas = ler_tabela(bruto, nome_arquivo)
    problemas, partidas = [], []
    for n, l in enumerate(linhas, start=2):
        try:
            d = para_data(l[col_data]).isoformat()
            deb = para_centavos(l[col_debito]) if l.get(col_debito) not in (None, "") else 0
            cred = para_centavos(l[col_credito]) if l.get(col_credito) not in (None, "") else 0
        except KeyError as exc:
            raise ErroEstrutural([f"coluna inexistente: {exc}"]) from exc
        except (ValueError, ValorInvalido) as exc:
            problemas.append(f"linha {n}: {exc}")
            continue
        conta = sanitizar_texto(l[col_conta])
        if not conta:
            problemas.append(f"linha {n}: conta vazia")
            continue
        if deb == 0 and cred == 0:
            continue
        partidas.append({"data": d, "conta": conta, "debito_centavos": abs(deb), "credito_centavos": abs(cred),
                         "historico": sanitizar_texto(l.get(col_historico)) if col_historico else None})
    if problemas:
        raise ErroEstrutural(problemas)
    return partidas
