#!/usr/bin/env python3
"""Pontuador estatístico de estilo (estilometria) para textos em português ou inglês.

Mede regularidades de superfície que costumam aparecer em texto padronizado:
frases de tamanho muito uniforme, fórmulas de transição, excesso de travessões,
tríades, contrastes do tipo "não apenas X, mas Y", parágrafos simétricos e
vocabulário pouco variado. Devolve um índice de 0 a 100.

LIMITES, para ler antes de usar o número:
- Não é detector de IA e não prova autoria. Texto jurídico, normativo ou
  institucional escrito por gente pontua alto com frequência.
- Os limiares e pesos abaixo foram escolhidos à mão. Não foram calibrados em
  nenhum corpus rotulado. O índice serve para comparar versões do MESMO texto
  (antes e depois de uma revisão), não para classificar textos isolados.
- Abaixo de ~150 palavras o resultado é instável e vem marcado como não confiável.

Uso:
    python3 pontuador_estatistico.py ARQUIVO [--json]
    python3 pontuador_estatistico.py ANTES --comparar DEPOIS [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

MIN_PALAVRAS = 150
JANELA_MATTR = 50

ABREVIACOES = {
    "art", "arts", "inc", "al", "n", "nº", "no", "p", "pp", "pág", "págs", "fl", "fls",
    "dr", "dra", "sr", "sra", "srs", "prof", "profa", "ex", "exa", "cf", "v", "vol",
    "ed", "obs", "etc", "ref", "tel", "av", "min", "des", "rel", "proc", "op", "cit",
    "mr", "mrs", "ms", "vs", "e.g", "i.e", "fig", "eq", "sec", "ch", "jr", "st",
}

CLICHES = [
    # português
    r"é importante (?:destacar|ressaltar|notar|observar|salientar|mencionar)",
    r"vale (?:ressaltar|destacar|lembrar|mencionar|a pena (?:destacar|notar))",
    r"cabe (?:ressaltar|destacar|salientar)", r"é fundamental", r"é crucial", r"é essencial",
    r"desempenha um papel", r"papel (?:fundamental|crucial|essencial)", r"em última análise",
    r"em suma", r"em resumo", r"em conclusão", r"dito isso", r"nesse sentido", r"neste sentido",
    r"além disso", r"ademais", r"por outro lado", r"no cenário atual", r"no mundo atual",
    r"cada vez mais", r"de forma (?:eficaz|eficiente|significativa|abrangente)",
    r"de maneira (?:eficaz|eficiente|significativa|abrangente)", r"mergulh(?:ar|e|ando) (?:em|no|na|fundo)",
    r"uma ampla gama", r"um leque de", r"navegar (?:por|pel[oa]s?|n[oa]s?)", r"jornada",
    r"robust[oa]s?", r"abrangentes?", r"potencializar", r"alavancar", r"fomentar",
    r"espero que (?:isso|isto) ajude", r"sinta-se à vontade", r"vamos explorar",
    # inglês
    r"it(?:'s| is) (?:important|worth) (?:to note|noting|mentioning)", r"plays? a (?:crucial|key|vital|pivotal) role",
    r"in conclusion", r"in summary", r"ultimately", r"furthermore", r"moreover", r"additionally",
    r"delve", r"tapestry", r"landscape", r"testament to", r"leverag(?:e|ing)", r"seamless(?:ly)?",
    r"robust", r"comprehensive", r"navigat(?:e|ing) the", r"in today's", r"i hope this helps",
    r"feel free to", r"let's (?:explore|dive)",
]
_RE_CLICHES = re.compile(r"(?<!\w)(?:" + "|".join(CLICHES) + r")(?!\w)", re.IGNORECASE)
_RE_CONTRASTE = re.compile(
    r"(?<!\w)(?:não (?:é |são |se trata )?(?:apenas|só|somente|meramente)\b[^.!?\n]{1,120}?\b(?:mas|e sim)\b"
    r"|not (?:just|only|merely)\b[^.!?\n]{1,120}?\bbut\b)", re.IGNORECASE)
_RE_TRIADE = re.compile(r"\b[\w-]+(?: [\w-]+)?, [\w-]+(?: [\w-]+)?,? (?:e|ou|and|or) [\w-]+", re.IGNORECASE)
_RE_PALAVRA = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
_RE_FIM_FRASE = re.compile(r"(?<=[.!?…])[\"”’»)\]]*\s+(?=[\"“‘«(\[]*[A-ZÀ-ÖØ-Þ0-9])")


def _sem_marcacao(texto: str) -> str:
    texto = re.sub(r"```.*?```", " ", texto, flags=re.DOTALL)
    texto = re.sub(r"`[^`\n]*`", " ", texto)
    texto = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", texto)
    texto = re.sub(r"<[^>\n]{1,200}>", " ", texto)
    texto = re.sub(r"^[ \t]*(?:#{1,6}|>+|[-*+]|\d+[.)])[ \t]+", "", texto, flags=re.MULTILINE)
    return re.sub(r"[*_~]{1,3}", "", texto)


def _frases(paragrafo: str) -> list[str]:
    frases: list[str] = []
    for parte in _RE_FIM_FRASE.split(paragrafo.strip()):
        parte = parte.strip()
        if not parte:
            continue
        if frases:
            ultima = frases[-1].rstrip(".").split()
            fim = ultima[-1].lower().strip("([\"“") if ultima else ""
            if frases[-1].endswith(".") and (fim in ABREVIACOES or (len(fim) == 1 and fim.isalpha())):
                frases[-1] += " " + parte
                continue
        frases.append(parte)
    return frases


def _cv(valores: list[int]) -> float | None:
    if len(valores) < 2:
        return None
    media = statistics.fmean(valores)
    return statistics.pstdev(valores) / media if media else None


def _mattr(palavras: list[str]) -> float | None:
    if len(palavras) < JANELA_MATTR:
        return None
    janelas = len(palavras) - JANELA_MATTR + 1
    return sum(len(set(palavras[i:i + JANELA_MATTR])) for i in range(janelas)) / (janelas * JANELA_MATTR)


def _rampa(valor: float | None, zero: float, um: float) -> float | None:
    """Mapeia `valor` para 0..1: 0 em `zero`, 1 em `um` (vale nos dois sentidos)."""
    if valor is None:
        return None
    return max(0.0, min(1.0, (valor - zero) / (um - zero)))


def pontuar(texto: str) -> dict:
    limpo = _sem_marcacao(texto)
    paragrafos = [p for p in re.split(r"\n\s*\n", limpo) if _RE_PALAVRA.search(p)]
    frases = [f for p in paragrafos for f in _frases(p) if _RE_PALAVRA.search(f)]
    palavras = [w.lower() for w in _RE_PALAVRA.findall(limpo)]
    n = len(palavras)
    if n == 0:
        return {"ok": False, "erro": "texto sem palavras", "palavras": 0}

    tam_frases = [len(_RE_PALAVRA.findall(f)) for f in frases]
    tam_paragrafos = [len(_RE_PALAVRA.findall(p)) for p in paragrafos]
    por_mil = 1000 / n
    cliches = [m.group(0).lower() for m in _RE_CLICHES.finditer(limpo)]
    contagem_cliches: dict[str, int] = {}
    for c in cliches:
        contagem_cliches[c] = contagem_cliches.get(c, 0) + 1
    aberturas = [(_RE_PALAVRA.findall(f) or [""])[0].lower() for f in frases]
    repetidas = sum(1 for a, b in zip(aberturas, aberturas[1:]) if a and a == b)

    metricas = {
        "palavras": n,
        "frases": len(frases),
        "paragrafos": len(paragrafos),
        "tamanho_medio_frase": round(statistics.fmean(tam_frases), 2) if tam_frases else None,
        "cv_tamanho_frase": _cv(tam_frases),
        "cv_tamanho_paragrafo": _cv(tam_paragrafos) if len(tam_paragrafos) >= 4 else None,
        "mattr_50": _mattr(palavras),
        "cliches_por_mil": len(cliches) * por_mil,
        "travessoes_por_mil": (limpo.count("—") + limpo.count(" – ")) * por_mil,
        "contrastes_por_mil": len(_RE_CONTRASTE.findall(limpo)) * por_mil,
        "triades_por_100_frases": len(_RE_TRIADE.findall(limpo)) * 100 / max(1, len(frases)),
        "ponto_e_virgula_por_mil": limpo.count(";") * por_mil,
        "aberturas_repetidas_seguidas": repetidas,
    }

    # (nome, valor 0..1 ou None, peso). Limiares escolhidos à mão; ver docstring.
    sinais = [
        ("frases_uniformes", _rampa(metricas["cv_tamanho_frase"], 0.60, 0.25), 25),
        ("formulas_e_cliches", _rampa(metricas["cliches_por_mil"], 0, 8), 25),
        ("travessoes", _rampa(metricas["travessoes_por_mil"], 1, 6), 10),
        ("triades", _rampa(metricas["triades_por_100_frases"], 5, 30), 10),
        ("contrastes_nao_apenas_mas", _rampa(metricas["contrastes_por_mil"], 0, 3), 10),
        ("paragrafos_uniformes", _rampa(metricas["cv_tamanho_paragrafo"], 0.60, 0.20), 10),
        ("vocabulario_pouco_variado", _rampa(metricas["mattr_50"], 0.75, 0.60), 10),
    ]
    aplicaveis = [(nome, v, peso) for nome, v, peso in sinais if v is not None]
    peso_total = sum(peso for _, _, peso in aplicaveis)
    indice = round(100 * sum(v * peso for _, v, peso in aplicaveis) / peso_total, 1) if peso_total else None

    return {
        "ok": True,
        "indice_padronizacao": indice,
        "escala": "0 = variado, 100 = muito padronizado",
        "confiavel": n >= MIN_PALAVRAS,
        "aviso": ("Heurística não calibrada: não detecta IA nem prova autoria. "
                  "Use para comparar versões do mesmo texto."
                  + ("" if n >= MIN_PALAVRAS else f" Texto curto (< {MIN_PALAVRAS} palavras): resultado instável.")),
        "sinais": {nome: {"valor": round(v, 3), "peso": peso} for nome, v, peso in aplicaveis},
        "sinais_nao_aplicaveis": [nome for nome, v, _ in sinais if v is None],
        "metricas": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in metricas.items()},
        "cliches_encontrados": dict(sorted(contagem_cliches.items(), key=lambda kv: -kv[1])),
    }


def _ler(caminho: str) -> str:
    dados = sys.stdin.buffer.read() if caminho == "-" else Path(caminho).read_bytes()
    return dados.decode("utf-8", errors="replace")


def _resumo(r: dict) -> str:
    if not r["ok"]:
        return f"erro: {r['erro']}"
    m = r["metricas"]
    linhas = [
        f"Índice de padronização: {r['indice_padronizacao']} / 100"
        + ("" if r["confiavel"] else "  (NÃO confiável: texto curto)"),
        f"{m['palavras']} palavras, {m['frases']} frases, {m['paragrafos']} parágrafos",
        "Sinais (0 a 1, com peso):",
    ]
    linhas += [f"  {nome}: {s['valor']} (peso {s['peso']})" for nome, s in r["sinais"].items()]
    if r["cliches_encontrados"]:
        linhas.append("Fórmulas encontradas: " + ", ".join(f"{k} x{v}" for k, v in r["cliches_encontrados"].items()))
    linhas.append(r["aviso"])
    return "\n".join(linhas)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Pontuador estatístico de estilo (heurístico).")
    p.add_argument("arquivo", help='arquivo de texto, ou "-" para a entrada padrão')
    p.add_argument("--comparar", metavar="DEPOIS", help="segunda versão, para ver a diferença")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        antes = pontuar(_ler(args.arquivo))
        depois = pontuar(_ler(args.comparar)) if args.comparar else None
    except OSError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2
    if depois is None:
        print(json.dumps(antes, ensure_ascii=False, indent=2) if args.json else _resumo(antes))
        return 0 if antes["ok"] else 2
    if not (antes["ok"] and depois["ok"]):
        print("erro: um dos textos não tem palavras.", file=sys.stderr)
        return 2
    delta = round(depois["indice_padronizacao"] - antes["indice_padronizacao"], 1)
    if args.json:
        print(json.dumps({"antes": antes, "depois": depois, "variacao_indice": delta}, ensure_ascii=False, indent=2))
    else:
        print(f"== ANTES ==\n{_resumo(antes)}\n\n== DEPOIS ==\n{_resumo(depois)}\n\nVariação do índice: {delta:+}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
