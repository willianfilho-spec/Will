"""Chaves que impedem lançamentos duplicados.

Dois problemas diferentes, duas chaves diferentes:

1. Reprocessar o mesmo extrato (ou extratos com períodos sobrepostos) não pode
   gerar lançamentos novos. Para isso, cada transação recebe uma `chave`
   estável: com FITID, a chave é (conta, FITID); sem FITID, é o conteúdo
   (conta, data, valor, histórico) mais o número de ocorrência daquele
   conteúdo dentro do arquivo.

   O número de ocorrência é o que permite duas operações legítimas iguais no
   mesmo dia (dois pagamentos de R$ 1.200,00 ao mesmo fornecedor): elas viram
   ocorrência 1 e 2, chaves distintas. Reprocessar o arquivo gera de novo 1 e
   2, e ambas já existem; nada é duplicado.

2. Alguns bancos geram FITIDs diferentes a cada download do mesmo período.
   Nesse caso a chave por FITID não reconhece a repetição. A `chave_conteudo`
   (sem FITID) serve de segunda barreira: se já existe no banco de dados uma
   transação com o mesmo conteúdo e outro FITID, o lançamento novo vai para
   revisão como "possível duplicidade" em vez de ser liberado.

Limitação conhecida: sem FITID, se o banco alterar o texto do histórico entre
um download e outro, a chave muda. Isso precisa ser verificado com extratos
reais de cada banco.
"""

from __future__ import annotations

import hashlib
from collections import Counter

from .modelo import Transacao
from .texto import normalizar


def _hash(*partes: str) -> str:
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()[:32]


def conteudo(t: Transacao) -> tuple[str, str, str, str, str]:
    # O número do documento entra no conteúdo: dois pagamentos iguais com
    # cheques/documentos diferentes são, com certeza, operações distintas.
    return (
        t.conta_bancaria,
        t.data.isoformat(),
        f"{t.valor:.2f}",
        normalizar(t.historico),
        normalizar(t.documento or ""),
    )


def calcular_chaves(transacoes: list[Transacao]) -> list[tuple[str, str, int]]:
    """Devolve, para cada transação, (chave, chave_conteudo, ocorrencia).

    `ocorrencia` é 1 para a primeira vez que o conteúdo aparece no arquivo,
    2 para a segunda, e assim por diante.
    """
    vistos: Counter[tuple[str, ...]] = Counter()
    resultado = []
    for t in transacoes:
        c = conteudo(t)
        vistos[c] += 1
        ocorrencia = vistos[c]
        chave_conteudo = _hash("conteudo", *c, str(ocorrencia))
        if t.fitid:
            chave = _hash("fitid", t.conta_bancaria, t.fitid)
        else:
            chave = chave_conteudo
        resultado.append((chave, chave_conteudo, ocorrencia))
    return resultado
