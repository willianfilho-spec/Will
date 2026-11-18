"""Leitor do Plano de Contas exportado do Fortes Contábil (CSV).

Formato conferido num arquivo real do escritório: sem cabeçalho, ponto e
vírgula, campos entre aspas, latin-1/cp1252, na ordem
classificação;descrição;reduzido;...;natureza. Exemplo:

    "1";"*** Ativo ***";;;X;"Devedora"
    "1.01.01.02.01.0001-8";"Banco Exemplo Ação";362;X;X;"Devedora"

Conta com código reduzido aceita lançamento (analítica); sem reduzido, é
sintética. Se o Fortes de outra empresa exportar diferente, o leitor recusa o
arquivo com a linha do problema em vez de adivinhar.
"""

from __future__ import annotations

import csv
import io

from parsers.comum import ErroEstrutural, decodificar, sanitizar_texto


def ler_plano_fortes(bruto: bytes) -> list[dict]:
    texto = decodificar(bruto)
    problemas, contas = [], []
    for n, campos in enumerate(csv.reader(io.StringIO(texto, newline=""), delimiter=";"), start=1):
        if not campos or not campos[0].strip():
            continue
        if n == 1 and campos[0].strip().lower() in ("classificacao", "classificação", "codigo", "código"):
            continue  # tolera cabeçalho
        if len(campos) < 3:
            problemas.append(f"linha {n}: esperados ao menos 3 campos (classificação, descrição, reduzido)")
            continue
        classificacao, descricao, reduzido = (c.strip() for c in campos[:3])
        if reduzido and not reduzido.isdigit():
            problemas.append(f"linha {n}: código reduzido {reduzido!r} não é numérico")
            continue
        natureza = next((c.strip() for c in reversed(campos) if c.strip().lower() in ("devedora", "credora")), None)
        contas.append({
            "classificacao": classificacao,
            "descricao": sanitizar_texto(descricao),
            "reduzido": reduzido or None,
            "aceita_lancamento": 1 if reduzido else 0,
            "natureza": natureza,
        })
    reduzidos = [c["reduzido"] for c in contas if c["reduzido"]]
    repetidos = sorted({r for r in reduzidos if reduzidos.count(r) > 1})
    if repetidos:
        problemas.append(f"código reduzido repetido no plano: {', '.join(repetidos)}")
    if problemas:
        raise ErroEstrutural(problemas)
    if not contas:
        raise ErroEstrutural(["nenhuma conta encontrada"])
    if not reduzidos:
        raise ErroEstrutural(["nenhuma conta analítica (com código reduzido) no plano"])
    return contas
