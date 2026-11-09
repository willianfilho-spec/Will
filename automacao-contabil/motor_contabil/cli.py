"""Linha de comando.

  python -m motor_contabil.cli importar extrato.ofx
  python -m motor_contabil.cli listar --status pendente
  python -m motor_contabil.cli aprovar <chave> [--conta 2.1.1.01.001]
  python -m motor_contabil.cli descartar <chave> --motivo "duplicado no extrato"
  python -m motor_contabil.cli exportar lancamentos.csv

Opções comuns: --banco-dados, --plano, --regras, --usuario, --ia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .banco import BancoDeDados
from .classificador_ia import ClassificadorClaude
from .motor import Motor
from .plano_contas import PlanoDeContas
from .regras import ConjuntoDeRegras

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"


def _motor(args) -> Motor:
    classificador = ClassificadorClaude() if args.ia else None
    return Motor(
        BancoDeDados(args.banco_dados),
        PlanoDeContas.carregar(args.plano),
        ConjuntoDeRegras.carregar(args.regras),
        classificador=classificador,
        usuario=args.usuario,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="motor_contabil", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--banco-dados", default="motor_contabil.db")
    p.add_argument("--plano", default=str(EXEMPLOS / "plano_contas.csv"))
    p.add_argument("--regras", default=str(EXEMPLOS / "regras.json"))
    p.add_argument("--usuario", default="operador")
    p.add_argument("--ia", action="store_true",
                   help="usa a IA para sugerir contas (requer pacote anthropic e credencial)")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("importar")
    s.add_argument("arquivo")
    s.add_argument("--conta-bancaria", help="obrigatório para CSV")

    s = sub.add_parser("listar")
    s.add_argument("--status", choices=["liberado", "pendente", "bloqueado", "descartado", "exportado"])

    s = sub.add_parser("aprovar")
    s.add_argument("chave")
    s.add_argument("--conta")
    s.add_argument("--historico")

    s = sub.add_parser("descartar")
    s.add_argument("chave")
    s.add_argument("--motivo", required=True)

    s = sub.add_parser("exportar")
    s.add_argument("destino")

    args = p.parse_args(argv)
    motor = _motor(args)
    try:
        if args.comando == "importar":
            print(motor.importar(args.arquivo, args.conta_bancaria).resumo())
        elif args.comando == "listar":
            for item in motor.listar(args.status):
                print(
                    f"{item['chave'][:12]}  {item['data']}  {item['valor']:>12}  "
                    f"{item['status']:<10} D:{item['conta_debito'] or '-':<14} "
                    f"C:{item['conta_credito'] or '-':<14} {item['historico_banco'][:40]}"
                )
                if item["motivos"]:
                    print(f"{'':14}motivo: {item['motivos']}")
        elif args.comando == "aprovar":
            chave = _resolver_chave(motor, args.chave)
            lanc = motor.aprovar(chave, args.conta, args.historico)
            print(f"{lanc.status.value}: {' | '.join(lanc.motivos) or 'ok'}")
        elif args.comando == "descartar":
            motor.descartar(_resolver_chave(motor, args.chave), args.motivo)
            print("descartado")
        elif args.comando == "exportar":
            lote, n = motor.exportar(args.destino)
            print(f"{n} lançamentos exportados" + (f" (lote {lote})" if lote else ""))
    except (ValueError, KeyError) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    finally:
        motor.banco.fechar()
    return 0


def _resolver_chave(motor: Motor, prefixo: str) -> str:
    """Aceita o prefixo de 12 caracteres mostrado por `listar`."""
    candidatas = [i["chave"] for i in motor.listar() if i["chave"].startswith(prefixo)]
    if len(candidatas) != 1:
        raise KeyError(f"prefixo {prefixo!r} corresponde a {len(candidatas)} lançamentos")
    return candidatas[0]


if __name__ == "__main__":
    sys.exit(main())
