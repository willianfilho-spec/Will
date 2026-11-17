#!/usr/bin/env python3
"""Hooks e verificador do sistema de memória (pasta memoria/).

Uso:
  memoria.py inicio      -> hook SessionStart: imprime o estado da memória
                            (vai para o contexto do Claude) e grava o HEAD inicial.
  memoria.py fim         -> hook Stop: se houve trabalho fora de memoria/ e a
                            memória não foi tocada, pede UMA revisão por sessão.
  memoria.py verificar   -> uso manual: checa tamanho, duplicatas, datas e
                            padrões sensíveis. Sai com código 1 se achar erro.

Princípio: falha da memória nunca bloqueia o Claude. Qualquer exceção nos
modos de hook termina com código 0 e silêncio. Só a biblioteca padrão é usada.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

RAIZ = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASTA = os.path.join(RAIZ, "memoria")
ARQUIVOS = ["preferencias.md", "pendencias.md", "projetos.md",
            "decisoes.md", "usuario.md", "historico.md"]
LIMITE_LINHAS = {"preferencias.md": 80, "pendencias.md": 80}  # importados no CLAUDE.md
LIMITE_PADRAO = 250
DIAS_DESATUALIZADO = 60
ESTADO = os.path.join(tempfile.gettempdir(), "claude-memoria")
LOG = os.path.join(ESTADO, "hooks.log")

# Padrões que não devem aparecer num repositório público.
SENSIVEIS = [
    ("e-mail", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("CPF", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("telefone", re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-\d{4}\b")),
    ("token GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("chave API", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,})")),
    ("senha", re.compile(r"(?i)\b(senha|password|token|api[_ -]?key)\s*[:=]\s*\S+")),
]
DATA = re.compile(r"\[(\d{4}-\d{2}-\d{2})\]")
ATUALIZADO = re.compile(r"(?i)atualizado em:\s*(\d{4}-\d{2}-\d{2})")


def log(msg):
    try:
        os.makedirs(ESTADO, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def git(*args):
    r = subprocess.run(["git", "-C", RAIZ, *args], capture_output=True,
                       text=True, timeout=5)
    return r.stdout.rstrip("\n") if r.returncode == 0 else ""


def ler_entrada():
    try:
        dados = sys.stdin.read()
        return json.loads(dados) if dados.strip() else {}
    except (ValueError, OSError):
        return {}


def arquivo_estado(sessao, nome):
    seguro = re.sub(r"[^A-Za-z0-9_-]", "", sessao or "sem-sessao")[:80]
    pasta = os.path.join(ESTADO, seguro)
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, nome)


def analisar():
    """Devolve (resumo_por_arquivo, avisos, erros)."""
    hoje = dt.date.today()
    resumo, avisos, erros = [], [], []
    if not os.path.isdir(PASTA):
        erros.append("pasta memoria/ ausente")
        return resumo, avisos, erros
    for nome in ARQUIVOS:
        caminho = os.path.join(PASTA, nome)
        if not os.path.isfile(caminho):
            avisos.append(f"{nome}: ausente")
            continue
        with open(caminho, encoding="utf-8") as f:
            linhas = f.read().splitlines()
        texto = "\n".join(linhas)
        m = ATUALIZADO.search(texto)
        datas = [m.group(1)] if m else []
        datas += DATA.findall(texto)
        ultima = max(datas) if datas else None
        resumo.append(f"{nome}: {len(linhas)} linhas, última data {ultima or 'nenhuma'}")
        limite = LIMITE_LINHAS.get(nome, LIMITE_PADRAO)
        if len(linhas) > limite:
            avisos.append(f"{nome}: {len(linhas)} linhas (limite {limite}); compactar")
        if ultima:
            try:
                idade = (hoje - dt.date.fromisoformat(ultima)).days
                if idade > DIAS_DESATUALIZADO and nome in ("pendencias.md", "projetos.md"):
                    avisos.append(f"{nome}: sem atualização há {idade} dias; revisar validade")
            except ValueError:
                avisos.append(f"{nome}: data inválida {ultima}")
        vistos = {}
        for i, linha in enumerate(linhas, 1):
            chave = re.sub(r"\s+", " ", DATA.sub("", linha)).strip().lower()
            if chave.startswith(("- ", "* ")) and len(chave) > 12:
                if chave in vistos:
                    avisos.append(f"{nome}:{i}: duplicata da linha {vistos[chave]}")
                else:
                    vistos[chave] = i
            for rotulo, padrao in SENSIVEIS:
                if padrao.search(linha):
                    erros.append(f"{nome}:{i}: possível {rotulo}; remover antes de commitar")
    return resumo, avisos, erros


def inicio():
    entrada = ler_entrada()
    sessao = entrada.get("session_id", "")
    head = git("rev-parse", "HEAD")
    if head and entrada.get("source", "startup") in ("startup", "resume", "clear"):
        caminho = arquivo_estado(sessao, "head_inicial")
        if not os.path.exists(caminho):  # idempotente: guarda só o primeiro
            with open(caminho, "w") as f:
                f.write(head)
    resumo, avisos, erros = analisar()
    partes = ["[Memória persistente] Instruções em CLAUDE.md. "
              "preferencias.md e pendencias.md já estão carregados; "
              "leia os demais arquivos de memoria/ só quando forem pertinentes à tarefa."]
    partes += ["Arquivos: " + "; ".join(resumo)] if resumo else []
    if avisos:
        partes.append("Avisos: " + "; ".join(avisos[:8]))
    if erros:
        partes.append("ERROS (tratar antes de commitar): " + "; ".join(erros[:8]))
    print("\n".join(partes))
    log(f"inicio sessao={sessao[:8]} avisos={len(avisos)} erros={len(erros)}")


def fim():
    entrada = ler_entrada()
    if entrada.get("stop_hook_active"):
        return  # evita laço: o Claude já está respondendo a um bloqueio
    sessao = entrada.get("session_id", "")
    marcador = arquivo_estado(sessao, "lembrete_dado")
    base_path = arquivo_estado(sessao, "head_inicial")
    if os.path.exists(marcador) or not os.path.exists(base_path):
        return
    with open(base_path) as f:
        base = f.read().strip()
    alterados = set(git("diff", "--name-only", base, "HEAD").splitlines())
    for linha in git("status", "--porcelain").splitlines():
        alterados.add(linha[3:].split(" -> ")[-1])
    alterados.discard("")
    fora = [a for a in alterados if not a.startswith("memoria/")]
    dentro = [a for a in alterados if a.startswith("memoria/")]
    if not fora or dentro:
        return
    with open(marcador, "w") as f:
        f.write("1")
    log(f"fim sessao={sessao[:8]} lembrete arquivos={len(fora)}")
    print(json.dumps({
        "decision": "block",
        "reason": ("[Memória] Esta sessão alterou arquivos do projeto "
                   f"({len(fora)}) e memoria/ não foi atualizada. Siga o "
                   "procedimento da skill salvar-memoria: registre apenas o que for "
                   "durável (decisões, estado de projeto, pendências, soluções "
                   "validadas). Se nada merecer registro, diga isso em uma linha e "
                   "encerre. Este lembrete aparece uma única vez por sessão."),
    }, ensure_ascii=False))


def verificar():
    resumo, avisos, erros = analisar()
    for r in resumo:
        print("ok    ", r)
    for a in avisos:
        print("aviso ", a)
    for e in erros:
        print("ERRO  ", e)
    print(f"\n{len(avisos)} aviso(s), {len(erros)} erro(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "verificar"
    if modo == "verificar":
        sys.exit(verificar())
    try:
        {"inicio": inicio, "fim": fim}[modo]()
    except Exception as exc:  # falha da memória não pode travar a sessão
        log(f"falha modo={modo}: {type(exc).__name__}: {exc}")
    sys.exit(0)
