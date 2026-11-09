"""Avalia o motor sobre planilhas "Despesas extrato" reais.

    python ferramentas/avaliar_planilhas.py <pasta-com-xlsx> [--conta 001-0000-00000-0]

Imprime apenas números agregados: nenhum nome de favorecido, CPF ou texto de
histórico sai no relatório. O banco de dados é criado numa pasta temporária e
apagado ao final. Nunca coloque as planilhas reais dentro do repositório.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas  # noqa: E402
from motor_contabil.idempotencia import conteudo  # noqa: E402
from motor_contabil.leitores.planilha_despesas import (  # noqa: E402
    ALERTA_DOIS_NOMES, ALERTA_SEM_TEXTO, ALERTA_SEM_TIPO, ler_planilha_despesas)
from motor_contabil.texto import normalizar  # noqa: E402

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"
MESES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO",
         "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]


def ordem(caminho: Path) -> int:
    nome = normalizar(caminho.name)
    return next((i for i, m in enumerate(MESES) if m in nome), 99)


def total_da_planilha(caminho: Path) -> Decimal | None:
    """Valor que o próprio Excel calculou na linha de total (se houver)."""
    import openpyxl

    aba = openpyxl.load_workbook(caminho, data_only=True).worksheets[0]
    formulas = openpyxl.load_workbook(caminho).worksheets[0]
    for linha in formulas.iter_rows():
        for c in linha:
            if isinstance(c.value, str) and c.value.upper().startswith("=SUM"):
                cache = aba[c.coordinate].value
                return Decimal(repr(cache)).quantize(Decimal("0.01")) if cache is not None else None
    return None


def pct(a: int, b: int) -> str:
    return f"{a} ({100 * a / b:.0f}%)" if b else "0"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--conta", default="BANCO-DA-EMPRESA")
    args = ap.parse_args()
    arquivos = sorted(Path(args.pasta).glob("*.xlsx"), key=ordem)
    if not arquivos:
        print("nenhum .xlsx encontrado")
        return 1

    with tempfile.TemporaryDirectory() as pasta:
        motor = Motor(BancoDeDados(Path(pasta) / "avaliacao.db"),
                      PlanoDeContas.carregar(EXEMPLOS / "plano_contas.csv"),
                      ConjuntoDeRegras.carregar(EXEMPLOS / "regras.json"))
        favorecidos_vistos: set[str] = set()
        problemas = 0
        print("# Avaliação do motor com planilhas reais\n")
        for arq in arquivos:
            ts = ler_planilha_despesas(arq, args.conta)
            soma = -sum(t.valor for t in ts)
            excel = total_da_planilha(arq)
            r1 = motor.importar(arq, args.conta)
            r2 = motor.importar(arq, args.conta)
            gravado = -sum(Decimal(i["valor"]) for i in motor.listar() if i["origem"] == arq.name)

            # duplicidade: com e sem a coluna DESCRIÇÃO
            def repetidas(itens):
                c = Counter(itens)
                return sum(n for n in c.values() if n > 1)
            com_desc = repetidas(conteudo(t) for t in ts)
            sem_desc = repetidas((t.data, f"{t.valor}", normalizar(t.historico)) for t in ts)

            lancs = [(t.historico, t.favorecido or "") for t in ts]
            sem_tipo = sum(1 for t in ts if ALERTA_SEM_TIPO in t.alertas or ALERTA_SEM_TEXTO in t.alertas)
            sem_favorecido = sum(1 for _, d in lancs if not d)
            dois_nomes = sum(1 for t in ts if ALERTA_DOIS_NOMES in t.alertas)

            pix = [normalizar(d) for l, d in lancs if "PIX" in l.upper() and d]
            recorrentes = sum(1 for d in pix if d in favorecidos_vistos)
            favorecidos_vistos.update(pix)

            itens = [i for i in motor.listar() if i["origem"] == arq.name]
            status = Counter(i["status"] for i in itens)
            motivos = Counter()
            for i in itens:
                for m in (i["motivos"] or "").split(" | "):
                    if m:
                        motivos[re.sub(r":.*", "", m)] += 1
            regras = Counter(i["fonte"] for i in itens if i["fonte"].startswith("regra"))

            # Nenhum PIX pode ser liberado automaticamente: a natureza do
            # pagamento a uma pessoa não se deduz do extrato.
            pix_liberados = sum(1 for i in itens if "PIX ENVIADO" in normalizar(i["historico_banco"])
                                and not normalizar(i["historico_banco"]).startswith(("TAR", "IOF"))
                                and i["status"] == "liberado")
            ok_soma = soma == gravado and (excel is None or excel == soma)
            ok_idem = r2.novas == 0 and r2.ja_importadas == r1.lidas
            problemas += (not ok_soma) + (not ok_idem) + (pix_liberados > 0)
            n = len(ts)
            print(f"## {arq.name}\n")
            print(f"- Período: {min(t.data for t in ts):%d/%m/%Y} a {max(t.data for t in ts):%d/%m/%Y}; {n} movimentações")
            print(f"- Soma lida: R$ {soma}; total do Excel: {'R$ ' + str(excel) if excel is not None else 'sem linha de total'}; "
                  f"gravado no motor: R$ {gravado} → {'CONFERE' if ok_soma else 'DIVERGE'}")
            print(f"- Reimportação do mesmo arquivo: {r2.novas} novas, {r2.ja_importadas} reconhecidas → {'OK' if ok_idem else 'FALHA'}")
            print(f"- Linhas em grupos idênticos (data+valor+texto): só texto do banco {pct(sem_desc, n)}; "
                  f"texto + DESCRIÇÃO {pct(com_desc, n)}")
            print(f"- Situação: liberado {status['liberado']}, pendente {status['pendente']}, bloqueado {status['bloqueado']}")
            print(f"- Motivos de pendência: {dict(motivos.most_common())}")
            print(f"- Classificadas por regra: {pct(sum(regras.values()), n)} {dict(regras)}")
            print(f"- PIX liberados automaticamente: {pix_liberados} → {'OK' if pix_liberados == 0 else 'FALHA'}")
            print(f"- Qualidade da entrada: texto sem tipo de operação {pct(sem_tipo, n)}; "
                  f"sem favorecido {pct(sem_favorecido, n)}; favorecido com 6+ palavras (possível junção de dois nomes) {pct(dois_nomes, n)}")
            print(f"- PIX com favorecido já visto em meses anteriores: {pct(recorrentes, len(pix))}\n")
        motor.banco.fechar()
    print("Resultado:", "sem falhas de integridade" if problemas == 0 else f"{problemas} FALHA(S)")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
