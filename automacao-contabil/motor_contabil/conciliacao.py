"""Conferência do banco: extrato x contabilidade.

Compara o extrato com os lançamentos que movimentam a conta do banco na
contabilidade (hoje, os arquivos já importados no Fortes) de duas formas:

1. Saldo: em cada fim de mês, saldo impresso no extrato x saldo contábil
   (soma dos débitos menos os créditos na conta do banco até a data).
2. Movimento a movimento: cada movimento do extrato procura um lançamento com
   a mesma data, o mesmo valor e o banco na partida certa. O que sobra de cada
   lado é listado. Saldo igual com sobras dos dois lados significa erros que se
   compensam, e não conciliação.

Gerar lançamentos a partir do extrato não é conciliar; isto é a conciliação.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .modelo import Transacao
from .texto import formatar_valor


@dataclass(frozen=True)
class LancamentoAceito:
    data: date
    debito: str
    credito: str
    valor: Decimal
    historico: str = ""
    origem: str = ""
    linha: int = 0


def ler_importados(caminho: str | Path) -> list[LancamentoAceito]:
    """Lê um arquivo de importação do Fortes (data;debito;credito;valor;historico;...)."""
    caminho = Path(caminho)
    aceitos = []
    for numero, linha in enumerate(caminho.read_bytes().decode("cp1252").splitlines(), start=1):
        if not linha.strip():
            continue
        campos = linha.split(";")
        if len(campos) < 5:
            raise ValueError(f"{caminho.name}, linha {numero}: esperado o leiaute do Fortes")
        try:
            data = datetime.strptime(campos[0], "%d/%m/%Y").date()
            valor = Decimal(campos[3].replace(".", "").replace(",", "."))
        except (ValueError, ArithmeticError) as erro:
            raise ValueError(f"{caminho.name}, linha {numero}: {erro}") from erro
        aceitos.append(LancamentoAceito(data, campos[1].strip(), campos[2].strip(), valor,
                                        campos[4].strip(), caminho.name, numero))
    return aceitos


def efeito_no_banco(a: LancamentoAceito, banco: str) -> Decimal:
    efeito = Decimal("0")
    if a.debito == banco:
        efeito += a.valor
    if a.credito == banco:
        efeito -= a.valor
    return efeito


def saldo_contabil(aceitos: list[LancamentoAceito], banco: str, ate: date,
                   saldo_inicial: Decimal = Decimal("0")) -> Decimal:
    return saldo_inicial + sum((efeito_no_banco(a, banco) for a in aceitos if a.data <= ate), Decimal("0"))


@dataclass
class Confronto:
    pareados: int = 0
    so_no_extrato: list[Transacao] = field(default_factory=list)
    so_na_contabilidade: list[LancamentoAceito] = field(default_factory=list)


def confrontar(transacoes: list[Transacao], aceitos: list[LancamentoAceito], banco: str,
               inicio: date | None = None, fim: date | None = None) -> Confronto:
    def no_periodo(d: date) -> bool:
        return (inicio is None or d >= inicio) and (fim is None or d <= fim)

    contabeis: dict[tuple, list[LancamentoAceito]] = defaultdict(list)
    for a in aceitos:
        efeito = efeito_no_banco(a, banco)
        if efeito and no_periodo(a.data):
            contabeis[(a.data, efeito)].append(a)
    resultado = Confronto()
    for t in transacoes:
        if not no_periodo(t.data):
            continue
        lista = contabeis.get((t.data, t.valor))
        if lista:
            lista.pop(0)
            resultado.pareados += 1
        else:
            resultado.so_no_extrato.append(t)
    resultado.so_na_contabilidade = sorted(
        (a for lista in contabeis.values() for a in lista), key=lambda a: (a.data, a.linha)
    )
    return resultado


@dataclass
class LinhaMensal:
    mes: str
    fim: date
    saldo_extrato: Decimal
    saldo_contabil: Decimal
    so_extrato: int
    so_contabil: int

    @property
    def diferenca(self) -> Decimal:
        return self.saldo_contabil - self.saldo_extrato


def resumo_mensal(transacoes: list[Transacao], saldos: dict[date, Decimal],
                  aceitos: list[LancamentoAceito], banco: str,
                  saldo_inicial_contabil: Decimal = Decimal("0")) -> list[LinhaMensal]:
    """Uma linha por mês do extrato, no último dia com saldo impresso daquele mês."""
    if not saldos:
        raise ValueError("o extrato não trouxe saldos impressos para conferir")
    fins: dict[str, date] = {}
    for d in sorted(saldos):
        fins[d.strftime("%Y-%m")] = d
    linhas = []
    for mes, fim in fins.items():
        inicio = fim.replace(day=1)
        c = confrontar(transacoes, aceitos, banco, inicio, fim)
        linhas.append(LinhaMensal(
            mes, fim, saldos[fim], saldo_contabil(aceitos, banco, fim, saldo_inicial_contabil),
            len(c.so_no_extrato), len(c.so_na_contabilidade),
        ))
    return linhas


def _brl(v: Decimal) -> str:
    return ("-" if v < 0 else "") + formatar_valor(v)


def main(argv: list[str] | None = None) -> int:
    from .leitores import ler_itau_pdf_completo

    p = argparse.ArgumentParser(description="Confere o extrato do banco com a contabilidade.")
    p.add_argument("--extrato", required=True, help="extrato Itaú em PDF")
    p.add_argument("--importados", required=True, nargs="+", help="arquivos já importados no Fortes")
    p.add_argument("--banco", required=True, help="código reduzido da conta do banco")
    p.add_argument("--saldo-inicial", default="0", help="saldo contábil antes do primeiro arquivo")
    args = p.parse_args(argv)

    extrato = ler_itau_pdf_completo(args.extrato, args.banco)
    aceitos = [a for arquivo in args.importados for a in ler_importados(arquivo)]
    print(f"Extrato: {len(extrato.transacoes)} movimentos; {extrato.dias_conferidos} saldos diários "
          "conferidos com a soma dos movimentos")
    print(f"{'Mês':8} {'Fim':10} {'Extrato':>14} {'Contábil':>14} {'Diferença':>12} "
          f"{'Só extrato':>10} {'Só contáb.':>10}")
    linhas = resumo_mensal(extrato.transacoes, extrato.saldos, aceitos, args.banco,
                           Decimal(args.saldo_inicial.replace(",", ".")))
    for l in linhas:
        print(f"{l.mes:8} {l.fim.strftime('%d/%m/%Y'):10} {_brl(l.saldo_extrato):>14} "
              f"{_brl(l.saldo_contabil):>14} {_brl(l.diferenca):>12} {l.so_extrato:>10} {l.so_contabil:>10}")
    total = confrontar(extrato.transacoes, aceitos, args.banco)
    print(f"\nMovimento a movimento: {total.pareados} pareados, {len(total.so_no_extrato)} só no extrato,"
          f" {len(total.so_na_contabilidade)} só na contabilidade")
    for t in total.so_no_extrato[:30]:
        print(f"  só no extrato:      {t.data.strftime('%d/%m/%Y')} {_brl(t.valor):>12}  {t.historico[:60]}")
    for a in total.so_na_contabilidade[:30]:
        print(f"  só na contabilidade: {a.data.strftime('%d/%m/%Y')} {_brl(efeito_no_banco(a, args.banco)):>12}"
              f"  {a.historico[:60]} ({a.origem}:{a.linha})")
    ok = all(l.diferenca == 0 for l in linhas) and not total.so_no_extrato and not total.so_na_contabilidade
    print("\nConciliado: saldo igual em todos os meses e nenhuma sobra." if ok
          else "\nNÃO conciliado: veja as diferenças acima.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
