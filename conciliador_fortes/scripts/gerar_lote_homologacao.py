"""Gera um arquivo de teste para descobrir o limite real do histórico no Fortes (item H2).

    python scripts/gerar_lote_homologacao.py --debito 259 --credito 362 --data 01/01/2026 \
        --prefixo HOM --saida lote_teste_historico.csv

Use SOMENTE numa empresa de teste do Fortes. Cada linha tem valor 0,01 e
histórico de tamanho conhecido (80 a 200), terminando pela marca. Depois de
importar, abra o Razão no Fortes e anote, para cada linha, se o histórico
apareceu inteiro e se a marca ficou no fim. O arquivo esperado sai ao lado
(…_esperado.csv) para a conferência.

O leiaute é o mesmo do exportador do app; só os históricos são de teste.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exporters.fortes_exporter import CAMPOS_VAZIOS_NO_FIM, validar_prefixo  # noqa: E402

TAMANHOS = (80, 90, 100, 110, 118, 120, 123, 128, 140, 150, 200)

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--debito", required=True, help="código reduzido da conta de débito (empresa de teste)")
ap.add_argument("--credito", required=True, help="código reduzido da conta de crédito (empresa de teste)")
ap.add_argument("--data", required=True, help="dd/mm/aaaa")
ap.add_argument("--prefixo", default="HOM")
ap.add_argument("--saida", type=Path, default=Path("lote_teste_historico.csv"))
a = ap.parse_args()
validar_prefixo(a.prefixo)
d = datetime.strptime(a.data, "%d/%m/%Y")
if not (a.debito.isdigit() and a.credito.isdigit()) or a.debito == a.credito:
    sys.exit("débito e crédito devem ser códigos reduzidos numéricos e diferentes")
linhas, esperado = [], []
for n, tam in enumerate(TAMANHOS, start=1):
    marca = f"[{a.prefixo}-{d:%Y%m}-{n:06d}]"
    corpo = f"TESTE LIMITE {tam} "
    corpo = (corpo + "X" * tam)[: tam - len(marca) - 1]
    hist = f"{corpo} {marca}"
    assert len(hist) == tam
    linhas.append(";".join([f"{d:%d/%m/%Y}", a.debito, a.credito, "0,01", hist] + [""] * CAMPOS_VAZIOS_NO_FIM))
    esperado.append({"linha": n, "tamanho": tam, "marca": marca, "historico": hist,
                     "apareceu_inteiro_no_fortes": "", "marca_no_fim": "", "observacao": ""})
a.saida.write_bytes("".join(l + "\r\n" for l in linhas).encode("ascii"))
saida_esp = a.saida.with_name(a.saida.stem + "_esperado.csv")
with open(saida_esp, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(esperado[0]), delimiter=";")
    w.writeheader()
    w.writerows(esperado)
print(f"{len(linhas)} linhas em {a.saida}; planilha de conferência em {saida_esp}")
print("Lembre: só em empresa de teste. Total lançado: R$ 0,%02d" % len(linhas))
