"""Sugere regras de classificação a partir do que o contador já lançou.

Junta cada movimento do extrato (ou planilha) com o lançamento que o
escritório já importou no Fortes para o mesmo movimento (mesma data, mesmo
valor, banco na partida certa) e vê qual contrapartida foi usada. Um
histórico vira regra só quando:

- aparece pelo menos `minimo` vezes;
- todas as vezes foi lançado na mesma conta;
- essa conta existe no plano, é analítica e não está na lista de contas que
  exigem decisão do contador (sócios, empréstimos, lucros etc.).

Histórico que já foi lançado em contas diferentes (por exemplo, o PIX ao mesmo
funcionário ora como salário, ora como bonificação) não vira regra: depende de
julgamento e vai para revisão.

O resultado é uma SUGESTÃO. As regras só passam a valer depois que o contador
revisar o arquivo gerado. Ele contém nomes de favorecidos: guarde-o junto com
os dados do cliente, nunca no repositório.

    python -m motor_contabil.sugerir_regras \\
        --plano plano_fortes.csv --importados lancamentos_aceitos.csv \\
        --banco 362 --nunca 113,375 --saida regras_sugeridas.json \\
        planilha_abril.xlsx planilha_maio.xlsx ...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .conciliacao import LancamentoAceito, ler_importados
from .leitores import ler_extrato
from .modelo import Transacao
from .plano_contas import PlanoDeContas
from .texto import normalizar

SEM_HISTORICO = "SEM HISTORICO NA PLANILHA"


def chave_historico(historico: str) -> str:
    """Histórico sem números variáveis (datas, competências, documentos)."""
    return re.sub(r"\d+", "#", normalizar(historico))


def padrao_de(chave: str) -> str:
    return "^" + re.escape(chave).replace("\\#", "#").replace("#", r"\d+") + "$"


def parear(transacoes: list[Transacao], aceitos: list[LancamentoAceito],
           banco: str) -> list[tuple[Transacao, str | None]]:
    """Para cada movimento, a contrapartida usada pelo escritório, ou None se não der para saber."""
    candidatos: dict[tuple, list[LancamentoAceito]] = defaultdict(list)
    for a in aceitos:
        if a.credito == banco:
            candidatos[(a.data, a.valor, "saida")].append(a)
        if a.debito == banco:
            candidatos[(a.data, a.valor, "entrada")].append(a)
    usados: Counter = Counter()
    resultado = []
    for t in transacoes:
        chave = (t.data, abs(t.valor), t.sentido)
        lista = candidatos.get(chave, [])
        contas = {(a.debito if t.sentido == "saida" else a.credito) for a in lista}
        if len(contas) == 1 and usados[chave] < len(lista):
            usados[chave] += 1
            resultado.append((t, contas.pop()))
        else:
            resultado.append((t, None))  # sem lançamento correspondente, ou ambíguo
    return resultado


def sugerir(pares: list[tuple[Transacao, str | None]], plano: PlanoDeContas,
            nunca: set[str], minimo: int = 2) -> tuple[list[dict], list[str]]:
    por_chave: dict[tuple[str, str], list[str]] = defaultdict(list)
    meses: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t, reduzido in pares:
        if reduzido is None or t.historico == SEM_HISTORICO:
            continue
        k = (chave_historico(t.historico), t.sentido)
        por_chave[k].append(reduzido)
        meses[k].add(t.data.strftime("%Y-%m"))
    regras, avisos = [], []
    for (chave, sentido), contas in sorted(por_chave.items()):
        distintas = set(contas)
        if len(contas) < minimo or len(distintas) > 1:
            continue
        reduzido = contas[0]
        if reduzido in nunca:
            continue
        conta = plano.por_reduzido(reduzido)
        if conta is None:
            avisos.append(f"{chave!r}: conta reduzida {reduzido} não está no plano informado")
            continue
        regras.append({
            "id": f"r{len(regras) + 1:03d}",
            "padrao": padrao_de(chave),
            "sentido": sentido,
            "conta": conta.codigo,
            "historico": None,
            "evidencia": f"{len(contas)} lançamentos na conta {reduzido} ({conta.descricao}),"
                         f" meses {', '.join(sorted(meses[(chave, sentido)]))}",
        })
    return regras, avisos


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sugere regras a partir de lançamentos já aceitos.")
    p.add_argument("arquivos", nargs="+", help="extratos ou planilhas (OFX, CSV, XLSX)")
    p.add_argument("--plano", required=True, help="plano de contas exportado do Fortes")
    p.add_argument("--importados", required=True, nargs="+", help="arquivos já aceitos pelo Fortes")
    p.add_argument("--banco", required=True, help="código reduzido da conta do banco")
    p.add_argument("--nunca", default="", help="reduzidos que exigem decisão do contador, separados por vírgula")
    p.add_argument("--minimo", type=int, default=2)
    p.add_argument("--saida", required=True)
    args = p.parse_args(argv)

    plano = PlanoDeContas.carregar_fortes(args.plano)
    conta_banco = plano.por_reduzido(args.banco)
    if conta_banco is None:
        print(f"erro: o reduzido {args.banco} não está no plano", file=sys.stderr)
        return 1
    transacoes = [t for arquivo in args.arquivos for t in ler_extrato(arquivo, args.banco)]
    aceitos = [a for arquivo in args.importados for a in ler_importados(arquivo)]
    pares = parear(transacoes, aceitos, args.banco)
    nunca = {n.strip() for n in args.nunca.split(",") if n.strip()}
    regras, avisos = sugerir(pares, plano, nunca, args.minimo)
    Path(args.saida).write_text(json.dumps(
        {"conta_banco": conta_banco.codigo, "regras": regras}, ensure_ascii=False, indent=1
    ), encoding="utf-8")
    pareados = sum(1 for _, r in pares if r)
    print(f"Movimentos lidos: {len(transacoes)}; com lançamento aceito identificado: {pareados}")
    print(f"Regras sugeridas: {len(regras)} (revisar antes de usar)")
    for aviso in avisos:
        print(f"aviso: {aviso}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
