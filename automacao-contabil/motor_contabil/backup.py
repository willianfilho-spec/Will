"""Backup local da pasta de dados do escritório, com restauração verificada.

A pasta de dados guarda os bancos SQLite (*.db) e os arquivos recebidos. Cada
cópia vira uma pasta `backup_AAAAMMDD_HHMMSS` no destino (de preferência
outro disco, pendrive ou unidade de rede), com um `manifesto.json` que lista
o tamanho e o hash SHA-256 de cada arquivo.

- Os bancos são copiados pela API de backup do SQLite, que gera uma cópia
  consistente mesmo com o aplicativo aberto. Copiar o arquivo .db direto pode
  pegar o banco no meio de uma gravação.
- A cópia é montada numa pasta provisória e só ganha o nome final depois de
  conferida. Uma cópia interrompida nunca é confundida com uma cópia boa.
- Retenção: a última cópia de cada um dos 30 dias mais recentes e a última de
  cada um dos 12 meses mais recentes. As demais são apagadas, sempre depois
  de a cópia nova estar pronta.
- Restaurar exige uma pasta vazia: nunca sobrescreve dados em uso.

    python -m motor_contabil.backup fazer     --dados DADOS --destino BACKUPS
    python -m motor_contabil.backup verificar --destino BACKUPS
    python -m motor_contabil.backup testar    --destino BACKUPS
    python -m motor_contabil.backup restaurar --destino BACKUPS --para PASTA_VAZIA [--copia NOME]
    python -m motor_contabil.backup situacao  --destino BACKUPS [--max-horas 26]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PADRAO_NOME = re.compile(r"^backup_(\d{8})_(\d{6})$")
MANIFESTO = "manifesto.json"
DIARIAS = 30
MENSAIS = 12


@dataclass(frozen=True)
class Copia:
    pasta: Path
    quando: datetime


def _hash(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _eh_sqlite(caminho: Path) -> bool:
    with open(caminho, "rb") as f:
        return f.read(16) == b"SQLite format 3\x00"


def _copiar_sqlite(origem: Path, destino: Path) -> None:
    fonte = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    alvo = sqlite3.connect(destino)
    try:
        fonte.backup(alvo)
    finally:
        alvo.close()
        fonte.close()


def _integridade(caminho: Path) -> str:
    try:
        conexao = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        try:
            return "; ".join(r[0] for r in conexao.execute("PRAGMA integrity_check"))
        finally:
            conexao.close()
    except sqlite3.DatabaseError as erro:
        return str(erro)


def listar(destino: str | Path) -> list[Copia]:
    """Cópias completas (com manifesto), da mais antiga para a mais recente."""
    destino = Path(destino)
    if not destino.is_dir():
        return []
    copias = []
    for pasta in destino.iterdir():
        m = PADRAO_NOME.match(pasta.name)
        if m and pasta.is_dir() and (pasta / MANIFESTO).is_file():
            copias.append(Copia(pasta, datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")))
    return sorted(copias, key=lambda c: c.quando)


def verificar(pasta: str | Path) -> list[str]:
    """Problemas encontrados numa cópia; lista vazia quando está íntegra."""
    pasta = Path(pasta)
    try:
        manifesto = json.loads((pasta / MANIFESTO).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        return [f"manifesto ilegível: {erro}"]
    problemas = []
    listados = set()
    for item in manifesto["arquivos"]:
        caminho = pasta / item["caminho"]
        listados.add(item["caminho"])
        if not caminho.is_file():
            problemas.append(f"falta {item['caminho']}")
            continue
        if caminho.stat().st_size != item["tamanho"] or _hash(caminho) != item["sha256"]:
            problemas.append(f"{item['caminho']} não confere com o manifesto")
            continue
        if item.get("sqlite") and (resultado := _integridade(caminho)) != "ok":
            problemas.append(f"{item['caminho']}: banco danificado ({resultado})")
    sobras = {
        p.relative_to(pasta).as_posix() for p in pasta.rglob("*") if p.is_file()
    } - listados - {MANIFESTO}
    problemas += [f"arquivo fora do manifesto: {s}" for s in sorted(sobras)]
    return problemas


def fazer(dados: str | Path, destino: str | Path, agora: datetime | None = None) -> Copia:
    dados, destino = Path(dados).resolve(), Path(destino).resolve()
    if not dados.is_dir():
        raise ValueError(f"pasta de dados não encontrada: {dados}")
    if destino == dados or dados in destino.parents:
        raise ValueError("o destino do backup não pode ficar dentro da pasta de dados")
    destino.mkdir(parents=True, exist_ok=True)
    agora = agora or datetime.now()
    nome = agora.strftime("backup_%Y%m%d_%H%M%S")
    if (destino / nome).exists():
        raise ValueError(f"já existe a cópia {nome}; aguarde um segundo e tente de novo")
    provisoria = Path(tempfile.mkdtemp(prefix=f".{nome}.", suffix=".parcial", dir=destino))
    try:
        arquivos = []
        for origem in sorted(p for p in dados.rglob("*") if p.is_file()):
            relativo = origem.relative_to(dados)
            if origem.name.endswith(("-journal", "-wal", "-shm")):
                continue  # parte do banco em uso; a API de backup já inclui o conteúdo
            alvo = provisoria / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            sqlite = _eh_sqlite(origem)
            if sqlite:
                _copiar_sqlite(origem, alvo)
            else:
                shutil.copy2(origem, alvo)
            arquivos.append({"caminho": relativo.as_posix(), "tamanho": alvo.stat().st_size,
                             "sha256": _hash(alvo), "sqlite": sqlite})
        (provisoria / MANIFESTO).write_text(json.dumps(
            {"criado_em": agora.isoformat(timespec="seconds"), "origem": str(dados),
             "arquivos": arquivos}, ensure_ascii=False, indent=1), encoding="utf-8")
        if problemas := verificar(provisoria):
            raise ValueError("a cópia não passou na conferência: " + "; ".join(problemas))
        os.replace(provisoria, destino / nome)
    except BaseException:
        shutil.rmtree(provisoria, ignore_errors=True)
        raise
    copia = Copia(destino / nome, agora)
    aplicar_retencao(destino)
    return copia


def aplicar_retencao(destino: str | Path, diarias: int = DIARIAS, mensais: int = MENSAIS) -> list[Path]:
    copias = listar(destino)
    manter: set[Path] = set()
    ultima_do_dia: dict[str, Copia] = {}
    ultima_do_mes: dict[str, Copia] = {}
    for c in copias:  # em ordem: a última de cada dia ou mês prevalece
        ultima_do_dia[c.quando.strftime("%Y-%m-%d")] = c
        ultima_do_mes[c.quando.strftime("%Y-%m")] = c
    manter |= {c.pasta for c in sorted(ultima_do_dia.values(), key=lambda c: c.quando)[-diarias:]}
    manter |= {c.pasta for c in sorted(ultima_do_mes.values(), key=lambda c: c.quando)[-mensais:]}
    if copias:
        manter.add(copias[-1].pasta)
    apagadas = []
    for c in copias:
        if c.pasta not in manter:
            shutil.rmtree(c.pasta)
            apagadas.append(c.pasta)
    return apagadas


def restaurar(copia: str | Path, para: str | Path) -> int:
    copia, para = Path(copia), Path(para)
    if para.exists() and any(para.iterdir()):
        raise ValueError(f"{para} não está vazia. Restaure numa pasta vazia e troque depois, "
                         "com o aplicativo fechado.")
    if problemas := verificar(copia):
        raise ValueError(f"a cópia {copia.name} está com problemas: " + "; ".join(problemas))
    manifesto = json.loads((copia / MANIFESTO).read_text(encoding="utf-8"))
    para.mkdir(parents=True, exist_ok=True)
    for item in manifesto["arquivos"]:
        alvo = para / item["caminho"]
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copia / item["caminho"], alvo)
        if _hash(alvo) != item["sha256"]:
            raise ValueError(f"{item['caminho']} mudou durante a restauração")
    return len(manifesto["arquivos"])


def testar_restauracao(destino: str | Path) -> tuple[Copia, int]:
    """Restaura a cópia mais recente numa pasta temporária e confere tudo."""
    copias = listar(destino)
    if not copias:
        raise ValueError("nenhuma cópia encontrada no destino")
    with tempfile.TemporaryDirectory() as pasta:
        n = restaurar(copias[-1].pasta, Path(pasta) / "restaurado")
        for banco in (Path(pasta) / "restaurado").rglob("*"):
            if banco.is_file() and _eh_sqlite(banco) and _integridade(banco) != "ok":
                raise ValueError(f"{banco.name}: banco restaurado danificado")
    return copias[-1], n


def horas_desde_ultima(destino: str | Path, agora: datetime | None = None) -> float | None:
    copias = listar(destino)
    if not copias:
        return None
    return ((agora or datetime.now()) - copias[-1].quando).total_seconds() / 3600


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backup da pasta de dados do escritório.")
    sub = p.add_subparsers(dest="comando", required=True)
    s = sub.add_parser("fazer")
    s.add_argument("--dados", required=True)
    s.add_argument("--destino", required=True)
    for nome in ("verificar", "testar", "situacao"):
        s = sub.add_parser(nome)
        s.add_argument("--destino", required=True)
        if nome == "situacao":
            s.add_argument("--max-horas", type=float, default=26)
    s = sub.add_parser("restaurar")
    s.add_argument("--destino", required=True)
    s.add_argument("--para", required=True)
    s.add_argument("--copia", help="nome da cópia; padrão: a mais recente")
    args = p.parse_args(argv)
    try:
        if args.comando == "fazer":
            copia = fazer(args.dados, args.destino)
            print(f"cópia criada e conferida: {copia.pasta}")
        elif args.comando == "verificar":
            ruins = 0
            for c in listar(args.destino):
                problemas = verificar(c.pasta)
                ruins += bool(problemas)
                print(f"{c.pasta.name}: {'ok' if not problemas else '; '.join(problemas)}")
            return 1 if ruins else 0
        elif args.comando == "testar":
            copia, n = testar_restauracao(args.destino)
            print(f"restauração de {copia.pasta.name} testada: {n} arquivos íntegros")
        elif args.comando == "restaurar":
            copias = {c.pasta.name: c for c in listar(args.destino)}
            if not copias:
                raise ValueError("nenhuma cópia encontrada no destino")
            nome = args.copia or max(copias.values(), key=lambda c: c.quando).pasta.name
            if nome not in copias:
                raise ValueError(f"cópia {nome} não encontrada")
            n = restaurar(copias[nome].pasta, args.para)
            print(f"{n} arquivos restaurados de {nome} em {args.para}")
        elif args.comando == "situacao":
            horas = horas_desde_ultima(args.destino)
            if horas is None or horas > args.max_horas:
                print("ATENÇÃO: " + ("nenhuma cópia encontrada" if horas is None
                                     else f"última cópia há {horas:.0f} horas"))
                return 1
            print(f"última cópia há {horas:.1f} horas")
    except (ValueError, OSError) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
