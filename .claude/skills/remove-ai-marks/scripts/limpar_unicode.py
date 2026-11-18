#!/usr/bin/env python3
"""Inspeção e limpeza de Unicode invisível em texto (Camada A).

Só usa a biblioteca padrão. Serve como módulo (`inspecionar`, `limpar`) e como CLI:

    python3 limpar_unicode.py inspecionar ARQUIVO [--json]
    python3 limpar_unicode.py limpar ARQUIVO [-o SAIDA | --no-lugar] [--nfkc]
                                             [--homoglifos] [--nbsp] [--json]

Use "-" como ARQUIVO para ler da entrada padrão.

O que é tratado: caracteres de largura zero, controles bidirecionais, caracteres
"tag", seletores de variação, hífen condicional, preenchedores invisíveis,
controles C0/C1, espaços exóticos e separadores de linha/parágrafo Unicode.
Aspas curvas, travessões e acentos são caracteres visíveis e legítimos: ficam
como estão.

Códigos de saída: 0 = nada suspeito / limpeza concluída; 1 = `inspecionar`
encontrou algo; 2 = erro de uso ou de leitura.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

LARGURA_ZERO = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x180E}
BIDI = {0x200E, 0x200F, 0x061C, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
OPERADORES_INVISIVEIS = set(range(0x2061, 0x2065))
PREENCHEDORES = {0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5}
ESPACOS_EXOTICOS = {0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000}
SEPARADORES_LINHA = {0x2028, 0x2029}
NBSP = 0x00A0
HIFEN_CONDICIONAL = 0x00AD
VS_EMOJI = {0xFE0E, 0xFE0F}

MAX_EXEMPLOS = 5

# Letras de outros alfabetos idênticas a letras latinas (só usadas com --homoglifos).
HOMOGLIFOS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "һ": "h",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "ο": "o", "Ο": "O", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ρ": "P", "Τ": "T", "Υ": "Y",
    "Χ": "X",
}
_LATINA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def _eh_tag(cp: int) -> bool:
    return 0xE0000 <= cp <= 0xE007F


def _eh_seletor_variacao(cp: int) -> bool:
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def _parece_emoji(cp: int) -> bool:
    return cp >= 0x1F000 or 0x2190 <= cp <= 0x2BFF or 0x3030 <= cp <= 0x329F


def _escrita_com_juncao(cp: int) -> bool:
    """Árabe, siríaco e escritas índicas usam ZWJ/ZWNJ de forma legítima."""
    return 0x0600 <= cp <= 0x077F or 0x0900 <= cp <= 0x0DFF or 0xFB50 <= cp <= 0xFDFF


def _classificar(texto: str, i: int, em_bandeira: bool, nbsp: bool):
    """Devolve (categoria, ação) para o caractere em `i`, ou (None, None).

    Ações: "remover", "espaco" (vira U+0020) ou "novalinha" (vira \\n).
    """
    cp = ord(texto[i])
    if cp < 0x80 and cp >= 0x20 and cp != 0x7F:
        return None, None
    ant = ord(texto[i - 1]) if i > 0 else 0
    prox = ord(texto[i + 1]) if i + 1 < len(texto) else 0

    if cp in (0x09, 0x0A, 0x0D):
        return None, None
    if cp < 0x20 or 0x7F <= cp <= 0x9F:
        return "controle", "remover"
    if cp == NBSP:
        return ("espaco_nao_separavel", "espaco") if nbsp else (None, None)
    if cp == HIFEN_CONDICIONAL:
        return "hifen_condicional", "remover"
    if cp in (0x200C, 0x200D):
        if _escrita_com_juncao(ant) and _escrita_com_juncao(prox):
            return None, None
        if cp == 0x200D and (_parece_emoji(ant) or ant in VS_EMOJI or 0x1F3FB <= ant <= 0x1F3FF) and _parece_emoji(prox):
            return None, None
        return "largura_zero", "remover"
    if cp in LARGURA_ZERO:
        return "largura_zero", "remover"
    if cp in BIDI:
        return "bidirecional", "remover"
    if cp in OPERADORES_INVISIVEIS:
        return "operador_invisivel", "remover"
    if cp in PREENCHEDORES:
        return "preenchedor_invisivel", "remover"
    if cp in ESPACOS_EXOTICOS:
        return "espaco_exotico", "espaco"
    if cp in SEPARADORES_LINHA:
        return "separador_de_linha", "novalinha"
    if _eh_tag(cp):
        return (None, None) if em_bandeira else ("caractere_tag", "remover")
    if cp in VS_EMOJI:
        if _parece_emoji(ant) or (prox == 0x20E3 and chr(ant) in "#*0123456789"):
            return None, None
        return "seletor_de_variacao", "remover"
    if _eh_seletor_variacao(cp):
        return "seletor_de_variacao", "remover"
    if unicodedata.category(texto[i]) == "Cf":
        return "outro_formatacao", "remover"
    return None, None


def _varrer(texto: str, nbsp: bool):
    """Gera (índice, categoria, ação) para cada caractere a tratar."""
    em_bandeira = False
    for i, ch in enumerate(texto):
        cp = ord(ch)
        if cp == 0x1F3F4:  # bandeira preta: pode iniciar sequência de tags (ex.: 🏴󠁧󠁢󠁥󠁮󠁧󠁿)
            em_bandeira = True
            continue
        if em_bandeira and not _eh_tag(cp):
            em_bandeira = False
        categoria, acao = _classificar(texto, i, em_bandeira, nbsp)
        if cp == 0xE007F:
            em_bandeira = False
        if categoria:
            yield i, categoria, acao


def _relatorio(texto: str, achados) -> dict:
    por_categoria: dict[str, int] = {}
    por_codigo: dict[int, dict] = {}
    linha, inicio_linha, cursor = 1, 0, 0
    for i, categoria, _ in achados:
        for j in range(cursor, i):
            if texto[j] == "\n":
                linha += 1
                inicio_linha = j + 1
        cursor = i
        por_categoria[categoria] = por_categoria.get(categoria, 0) + 1
        cp = ord(texto[i])
        item = por_codigo.setdefault(cp, {
            "codigo": f"U+{cp:04X}",
            "nome": unicodedata.name(texto[i], "<sem nome>"),
            "categoria": categoria,
            "ocorrencias": 0,
            "exemplos": [],
        })
        item["ocorrencias"] += 1
        if len(item["exemplos"]) < MAX_EXEMPLOS:
            item["exemplos"].append({"linha": linha, "coluna": i - inicio_linha + 1})
    total = sum(por_categoria.values())
    return {
        "suspeito": total > 0,
        "total": total,
        "por_categoria": dict(sorted(por_categoria.items())),
        "caracteres": sorted(por_codigo.values(), key=lambda d: -d["ocorrencias"]),
    }


def inspecionar(texto: str, nbsp: bool = False) -> dict:
    """Relata o Unicode invisível/anômalo sem alterar o texto."""
    rel = _relatorio(texto, list(_varrer(texto, nbsp)))
    rel["tamanho"] = len(texto)
    rel["nbsp_presentes"] = texto.count(chr(NBSP))
    return rel


def _trocar_homoglifos(texto: str):
    trocas = 0

    def troca(m: re.Match) -> str:
        nonlocal trocas
        palavra = m.group(0)
        if not _LATINA.search(palavra):
            return palavra
        estranhos = [c for c in palavra if ord(c) > 0x24F and c.isalpha()]
        if not estranhos or any(c not in HOMOGLIFOS for c in estranhos):
            return palavra
        trocas += len(estranhos)
        return "".join(HOMOGLIFOS.get(c, c) for c in palavra)

    return re.sub(r"\w+", troca, texto), trocas


def limpar(texto: str, nfkc: bool = False, homoglifos: bool = False, nbsp: bool = False):
    """Devolve (texto_limpo, relatório).

    nfkc       aplica normalização NFKC ao final (desfaz ligaduras, letras de
               largura total etc.; também altera símbolos como ² e ™).
    homoglifos troca letras cirílicas/gregas idênticas a latinas, só em palavras
               que misturam alfabetos.
    nbsp       converte o espaço não separável (U+00A0) em espaço comum.
    """
    achados = list(_varrer(texto, nbsp))
    rel = _relatorio(texto, achados)
    acoes = {i: acao for i, _, acao in achados}
    troca = {"remover": "", "espaco": " ", "novalinha": "\n"}
    limpo = "".join(troca[acoes[i]] if i in acoes else ch for i, ch in enumerate(texto))

    rel["homoglifos_trocados"] = 0
    if homoglifos:
        limpo, rel["homoglifos_trocados"] = _trocar_homoglifos(limpo)
    rel["nfkc_aplicado"] = False
    if nfkc:
        normalizado = unicodedata.normalize("NFKC", limpo)
        rel["nfkc_aplicado"] = True
        rel["nfkc_alterou"] = normalizado != limpo
        limpo = normalizado

    rel["alterado"] = limpo != texto
    rel["tamanho_antes"] = len(texto)
    rel["tamanho_depois"] = len(limpo)
    rel["residuo"] = inspecionar(limpo, nbsp)["total"]
    return limpo, rel


def _ler(caminho: str) -> str:
    dados = sys.stdin.buffer.read() if caminho == "-" else Path(caminho).read_bytes()
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError as erro:
        raise SystemExit(f"erro: {caminho} não é UTF-8 válido ({erro}). Converta o arquivo antes.") from None


def _resumo(rel: dict) -> str:
    if not rel["total"]:
        return "Nenhum caractere invisível ou anômalo encontrado."
    linhas = [f"{rel['total']} caractere(s) a tratar:"]
    for c in rel["caracteres"]:
        ex = ", ".join(f"{e['linha']}:{e['coluna']}" for e in c["exemplos"])
        linhas.append(f"  {c['codigo']} {c['nome']} [{c['categoria']}] x{c['ocorrencias']} (linha:coluna {ex})")
    return "\n".join(linhas)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Inspeciona e limpa Unicode invisível em texto.")
    sub = p.add_subparsers(dest="comando", required=True)
    pi = sub.add_parser("inspecionar", help="relata sem alterar")
    pl = sub.add_parser("limpar", help="grava uma cópia limpa")
    for s in (pi, pl):
        s.add_argument("arquivo", help='caminho do arquivo, ou "-" para a entrada padrão')
        s.add_argument("--nbsp", action="store_true", help="tratar U+00A0 como espaço comum")
        s.add_argument("--json", action="store_true", help="relatório em JSON")
    pl.add_argument("-o", "--saida", help="arquivo de saída (padrão: NOME.cleaned.EXT)")
    pl.add_argument("--no-lugar", action="store_true", help="sobrescreve o arquivo original")
    pl.add_argument("--nfkc", action="store_true", help="normalização NFKC ao final")
    pl.add_argument("--homoglifos", action="store_true", help="troca letras cirílicas/gregas idênticas a latinas")
    args = p.parse_args(argv)

    try:
        texto = _ler(args.arquivo)
    except OSError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    if args.comando == "inspecionar":
        rel = inspecionar(texto, args.nbsp)
        print(json.dumps(rel, ensure_ascii=False, indent=2) if args.json else _resumo(rel))
        return 1 if rel["suspeito"] else 0

    limpo, rel = limpar(texto, nfkc=args.nfkc, homoglifos=args.homoglifos, nbsp=args.nbsp)
    if args.arquivo == "-" and not args.saida:
        sys.stdout.write(limpo)
        print(json.dumps(rel, ensure_ascii=False) if args.json else _resumo(rel), file=sys.stderr)
        return 0
    if args.no_lugar and args.saida:
        print("erro: use -o ou --no-lugar, não os dois.", file=sys.stderr)
        return 2
    origem = Path(args.arquivo)
    destino = origem if args.no_lugar else Path(args.saida) if args.saida else origem.with_name(
        f"{origem.stem}.cleaned{origem.suffix}")
    destino.write_bytes(limpo.encode("utf-8"))
    rel["saida"] = str(destino)
    print(json.dumps(rel, ensure_ascii=False, indent=2) if args.json else f"{_resumo(rel)}\nGravado em: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
