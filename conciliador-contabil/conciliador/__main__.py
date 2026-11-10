"""Ponto de entrada:  python -m conciliador extrato.csv"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from .exportador import exportar
from .ia import ErroIA, sugerir_contas
from .leitor import ErroExtrato, ler_extrato
from .pipeline import ErroIntegridade, conciliar, verificar_integridade
from .regras import ErroConfiguracao, carregar_configuracao, regras_que_casam

RAIZ = Path(__file__).resolve().parent.parent


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(
        prog="conciliador",
        description="Converte um extrato bancário (CSV) em lançamentos contábeis.",
    )
    parser.add_argument("extrato", help="arquivo CSV do extrato")
    parser.add_argument("--regras", default=RAIZ / "config" / "regras.json")
    parser.add_argument("--plano", default=RAIZ / "config" / "plano_de_contas.csv")
    parser.add_argument("--saida", default="saida", help="pasta dos arquivos gerados")
    parser.add_argument("--ia", action="store_true",
                        help="pede sugestão à IA para o que as regras não classificarem")
    args = parser.parse_args(argumentos)

    try:
        config = carregar_configuracao(args.regras, args.plano)
        transacoes, saldos_ignorados = ler_extrato(args.extrato)

        sugestoes = {}
        if args.ia:
            sem_regra = [t for t in transacoes if not regras_que_casam(t, config.regras)]
            print(f"Consultando a IA para {len(sem_regra)} movimento(s) sem regra...")
            sugestoes = sugerir_contas(sem_regra, config.plano)

        lancamentos = conciliar(transacoes, config, sugestoes)
        soma = verificar_integridade(transacoes, lancamentos, config)
        arquivo_todos, arquivo_revisao = exportar(lancamentos, args.saida)
    except (ErroExtrato, ErroConfiguracao, ErroIA, ErroIntegridade) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1

    por_status = Counter(l.status for l in lancamentos)
    total = len(lancamentos)
    print(f"Extrato: {args.extrato}")
    print(f"  Movimentos lidos ........ {total}  (linhas de saldo ignoradas: {saldos_ignorados})")
    for status in ("CLASSIFICADO", "REVISAR", "PENDENTE"):
        quantidade = por_status.get(status, 0)
        print(f"  {status:<12} ............ {quantidade:>3}  ({quantidade / total:.0%})")
    print(f"  Movimento líquido do banco: {soma:.2f}  (confere com o extrato)")
    print(f"Arquivos gerados:\n  {arquivo_todos}\n  {arquivo_revisao}")
    print("Atenção: revise os lançamentos antes de importar. A responsabilidade técnica é do contador.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
