"""Teste de restauração em pasta isolada. Gera o JSON que serve de evidência do item H4.

    python scripts/teste_restauracao.py [--data-dir PASTA] [--saida restauracao.json] [--manter]

A pasta de dados de origem só é lida. A cópia restaurada fica numa pasta
temporária, apagada no fim (use --manter para inspecionar).
Código de saída: 0 aprovado, 1 reprovado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from storage.restauracao import executar, salvar  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
ap.add_argument("--saida", type=Path, default=Path("restauracao.json"))
ap.add_argument("--manter", action="store_true", help="não apagar a pasta restaurada")
a = ap.parse_args()
r = executar(a.data_dir, a.manter)
salvar(r, a.saida)
for v in r["verificacoes"]:
    print(f"[{v['resultado'].upper():5}] {v['teste']}  {v['detalhe']}")
print(f"\nResultado: {r['resultado'].upper()}  ·  relatório em {a.saida}")
if r["origem_sintetica"]:
    print("Atenção: a pasta tem só usuários de demonstração; não vale como evidência do H4.")
sys.exit(0 if r["resultado"] == "aprovado" else 1)
