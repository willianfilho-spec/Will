"""Pré-validação de lotes JÁ GERADOS (leiaute de importação do Fortes). Roda local, sobre os seus arquivos.

    python scripts/validar_lote_existente.py LOTE.csv [LOTE2.csv ...] \
        [--plano plano.csv] [--banco 362] \
        [--saldo 2025-12-31=43028,71 --saldo 2026-10-27=-388,80] [--limite-historico 118]

O que confere (tudo automatizado; nada disto substitui importar no Fortes):
  - estrutura: 9 campos, ASCII, fim de linha CRLF, data e valor válidos, valor positivo, débito diferente de crédito;
  - duplicidade: linhas idênticas (erro); marca repetida em lançamentos diferentes (aviso: é o padrão de reclassificação);
  - plano (se --plano): toda conta existe e aceita lançamento;
  - tamanho do histórico em relação ao limite;
  - saldo da conta do banco em cada data pedida (--saldo), somando todos os arquivos informados.
Saída: só contagens e problemas com número de linha; nenhum histórico, valor de cliente ou nome é impresso.
Código de saída 0 = nenhum problema, 1 = há problemas. "Sem problemas aqui" NÃO é "aceito pelo Fortes".
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.money import formatar_br, para_centavos  # noqa: E402
from parsers.comum import para_data  # noqa: E402
from parsers.fortes_plano_parser import ler_plano_fortes  # noqa: E402

TAG = re.compile(r"\[([A-Z0-9]{2,6}-[0-9]{3,6}(?:-[0-9]{3,6})?)\]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lotes", nargs="+", type=Path)
    ap.add_argument("--plano", type=Path)
    ap.add_argument("--banco", help="código reduzido da conta do banco (para --saldo)")
    ap.add_argument("--saldo", action="append", default=[], help="AAAA-MM-DD=valor esperado (ex.: 2025-12-31=43028,71)")
    ap.add_argument("--limite-historico", type=int, default=118)
    a = ap.parse_args()
    plano = None
    if a.plano:
        contas = ler_plano_fortes(a.plano.read_bytes())
        plano = {c["reduzido"]: c for c in contas if c["reduzido"]}
    problemas, linhas_vistas, tags = [], Counter(), Counter()
    movimento: list[tuple[str, int]] = []
    total = 0
    for caminho in a.lotes:
        bruto = caminho.read_bytes()
        if not bruto.endswith(b"\r\n") or b"\n" in bruto.replace(b"\r\n", b""):
            problemas.append(f"{caminho.name}: fim de linha não é CRLF em todas as linhas")
        if any(b > 127 for b in bruto):
            problemas.append(f"{caminho.name}: há byte fora do ASCII")
        for n, linha in enumerate(bruto.decode("latin-1").split("\r\n"), start=1):
            if not linha.strip():
                continue
            total += 1
            c = linha.split(";")
            loc = f"{caminho.name} linha {n}"
            if len(c) != 9:
                problemas.append(f"{loc}: {len(c)} campos (esperados 9)")
                continue
            try:
                d = para_data(c[0]).isoformat()
                v = para_centavos(c[3])
            except Exception as exc:  # noqa: BLE001
                problemas.append(f"{loc}: {exc}")
                continue
            if v <= 0:
                problemas.append(f"{loc}: valor não positivo")
            if c[1] == c[2]:
                problemas.append(f"{loc}: débito igual a crédito ({c[1]})")
            if len(c[4]) > a.limite_historico:
                problemas.append(f"{loc}: histórico com {len(c[4])} caracteres (limite {a.limite_historico})")
            if not c[1].strip() or not c[2].strip():
                problemas.append(f"{loc}: conta vazia")
            if plano is not None:
                for papel, red in (("débito", c[1]), ("crédito", c[2])):
                    if red not in plano:
                        problemas.append(f"{loc}: conta de {papel} {red!r} não existe no plano")
                    elif not plano[red]["aceita_lancamento"]:
                        problemas.append(f"{loc}: conta de {papel} {red} é sintética")
            linhas_vistas[linha] += 1
            for t in TAG.findall(c[4]):
                tags[t] += 1
            if a.banco:
                if c[1] == a.banco:
                    movimento.append((d, v))
                elif c[2] == a.banco:
                    movimento.append((d, -v))
    problemas += [f"linha idêntica repetida {n}x (conteúdo omitido)" for l, n in linhas_vistas.items() if n > 1]
    # Marca repetida em lançamentos DIFERENTES é o padrão de reclassificação (o ajuste reaproveita a marca do
    # movimento original). É aviso, não erro. Linha idêntica repetida continua sendo erro (acima).
    avisos = [f"marca {t} aparece {n} vezes (reclassificação reaproveitando a marca? confirme se é intencional)"
              for t, n in tags.items() if n > 1]
    print(f"{len(a.lotes)} arquivo(s), {total} lançamentos, {len(tags)} marcas distintas")
    for s in a.saldo:
        data, esperado = s.split("=", 1)
        if not a.banco:
            problemas.append("--saldo exige --banco")
            break
        obtido = sum(v for d, v in movimento if d <= data)
        esp = para_centavos(esperado)
        ok = obtido == esp
        print(f"saldo da conta {a.banco} até {data}: {formatar_br(obtido)} (esperado {formatar_br(esp)}) -> {'BATE' if ok else 'NÃO BATE'}")
        if not ok:
            problemas.append(f"saldo em {data} difere em {formatar_br(obtido - esp)}")
    if avisos:
        print(f"\n{len(avisos)} aviso(s) (não impedem):")
        for av in avisos[:30]:
            print(" ~", av)
    if problemas:
        print(f"\n{len(problemas)} problema(s):")
        for p in problemas[:100]:
            print(" -", p)
        return 1
    print("\nNenhum problema encontrado. Isto NÃO é aceitação pelo Fortes: importe numa empresa de teste.")
    return 0


sys.exit(main())
