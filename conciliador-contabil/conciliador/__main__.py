"""Ponto de entrada:  python -m conciliador extrato.csv"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from .exportador import (
    ErroLayout, carregar_layout, exportar_conferencia, exportar_importacao,
    gravar_auditoria, ha_aprovacoes, ler_revisao,
)
from .ia import ErroIA, sugerir_contas
from .leitor import ErroExtrato, converter_valor, ler_extrato
from .modelos import STATUS_LIBERADOS
from .pipeline import ErroIntegridade, ErroRevisao, aplicar_revisao, conciliar, conferir_saldo, verificar_integridade
from .regras import ErroConfiguracao, carregar_configuracao, regras_que_casam

RAIZ = Path(__file__).resolve().parent.parent


def _valor(texto):
    try:
        return converter_valor(texto)
    except ValueError as erro:
        raise argparse.ArgumentTypeError(str(erro)) from erro


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(
        prog="conciliador",
        description="Converte um extrato bancário (CSV ou XLSX) em lançamentos contábeis.",
    )
    parser.add_argument("extrato", help="arquivo CSV ou XLSX do extrato")
    parser.add_argument("--regras", default=RAIZ / "config" / "regras.json")
    parser.add_argument("--plano", default=RAIZ / "config" / "plano_de_contas.csv")
    parser.add_argument("--layout", default=RAIZ / "config" / "layout_importacao.json",
                        help="layout do arquivo de importação do sistema contábil")
    parser.add_argument("--saida", default="saida", help="pasta dos arquivos gerados")
    parser.add_argument("--revisao", help="planilha de revisão preenchida (linhas com status APROVADO)")
    parser.add_argument("--saldo-inicial", type=_valor, help="saldo inicial, se o arquivo não trouxer")
    parser.add_argument("--saldo-final", type=_valor, help="saldo final, se o arquivo não trouxer")
    parser.add_argument("--ia", action="store_true",
                        help="pede sugestão à IA para o que as regras não classificarem")
    args = parser.parse_args(argumentos)

    pasta = Path(args.saida)
    revisao_existente = pasta / "revisao.csv"
    try:
        if not args.revisao and ha_aprovacoes(revisao_existente):
            raise ErroRevisao(
                f"{revisao_existente} tem linhas APROVADO que seriam perdidas. "
                f"Rode com --revisao {revisao_existente} ou escolha outra pasta em --saida."
            )
        config = carregar_configuracao(args.regras, args.plano)
        layout = carregar_layout(args.layout)
        extrato = ler_extrato(args.extrato)
        saldo = conferir_saldo(extrato, args.saldo_inicial, args.saldo_final)

        sugestoes = {}
        if args.ia:
            sem_regra = [t for t in extrato.transacoes if not regras_que_casam(t, config.regras)]
            print(f"Consultando a IA para {len(sem_regra)} movimento(s) sem regra...")
            sugestoes = sugerir_contas(sem_regra, config.plano)

        lancamentos = conciliar(extrato.transacoes, config, sugestoes)
        alteracoes = aplicar_revisao(lancamentos, ler_revisao(args.revisao), config) if args.revisao else []
        soma = verificar_integridade(extrato.transacoes, lancamentos, config)

        arquivo_todos, arquivo_revisao = exportar_conferencia(lancamentos, pasta)
        a_resolver = [l for l in lancamentos if l.status not in STATUS_LIBERADOS]
        arquivo_importacao = pasta / layout.get("arquivo", "importacao.csv")
        if a_resolver:
            # Nunca deixar para trás um arquivo de importação de uma rodada anterior.
            arquivo_importacao.unlink(missing_ok=True)
            arquivo_importacao = None
        else:
            arquivo_importacao = exportar_importacao(lancamentos, layout, pasta)
        arquivo_auditoria = gravar_auditoria(
            pasta, saldo=saldo, lancamentos=lancamentos, alteracoes=alteracoes,
            arquivo_importacao=arquivo_importacao,
            arquivos_entrada={"extrato": args.extrato, "regras": args.regras, "plano": args.plano,
                              "layout": args.layout, "revisao": args.revisao},
        )
    except (ErroExtrato, ErroConfiguracao, ErroIA, ErroIntegridade, ErroRevisao, ErroLayout) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1

    por_status = Counter(l.status for l in lancamentos)
    total = len(lancamentos)
    print(f"Extrato: {args.extrato}")
    print(f"  Movimentos lidos: {total}   (linhas de saldo: {extrato.linhas_saldo})")
    print(f"  Conferência de saldo: {saldo}")
    for status in ("CLASSIFICADO", "APROVADO", "REVISAR", "PENDENTE"):
        if status in por_status or status != "APROVADO":
            quantidade = por_status.get(status, 0)
            print(f"  {status:<13}{quantidade:>4}  ({quantidade / total:.0%})")
    print(f"  Movimento líquido do banco nos lançamentos: {soma:.2f}  (igual ao do extrato)")
    print(f"Arquivos:\n  {arquivo_todos}\n  {arquivo_revisao}\n  {arquivo_auditoria}")
    if arquivo_importacao:
        print(f"  {arquivo_importacao}   <- arquivo de importação")
        if layout.get("validado_no_sistema") is not True:
            print("AVISO: o layout de importação ainda não foi validado no sistema contábil "
                  "(ver config/layout_importacao.json).")
    else:
        print(f"Arquivo de importação NÃO gerado: {len(a_resolver)} lançamento(s) aguardam revisão.\n"
              f"  Abra {arquivo_revisao}, ajuste as contas, troque o status para APROVADO e rode de novo\n"
              f"  com --revisao {arquivo_revisao}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
