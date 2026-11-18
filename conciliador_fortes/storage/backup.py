"""Backup consistente (API de backup do SQLite) e verificação de integridade.

Cada backup é uma pasta com os bancos e um manifesto com SHA-256. Os arquivos
originais enviados também são copiados, porque o banco aponta para eles.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import config


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _copiar_sqlite(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(origem)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def integridade(caminho: Path) -> str:
    con = sqlite3.connect(caminho)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def criar_backup(data_dir: Path | None = None, destino_raiz: Path | None = None) -> Path:
    data_dir = Path(data_dir or config.DATA_DIR)
    destino_raiz = Path(destino_raiz or (data_dir / "backups"))
    pasta = destino_raiz / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    arquivos: dict[str, str] = {}
    central = data_dir / "central.db"
    if central.exists():
        _copiar_sqlite(central, pasta / "central.db")
    for db in sorted((data_dir / "empresas").glob("*/contabil.db")):
        rel = db.relative_to(data_dir)
        _copiar_sqlite(db, pasta / rel)
        originais = db.parent / "arquivos"
        if originais.exists():
            shutil.copytree(originais, pasta / rel.parent / "arquivos", dirs_exist_ok=True)
    for f in sorted(p for p in pasta.rglob("*") if p.is_file()):
        arquivos[str(f.relative_to(pasta))] = _sha256(f)
    (pasta / "manifesto.json").write_text(
        json.dumps({"criado_em": datetime.now().isoformat(), "arquivos": arquivos}, indent=1),
        encoding="utf-8",
    )
    return pasta


def verificar_backup(pasta: Path) -> list[str]:
    """Lista de problemas; vazia quando o backup está íntegro."""
    pasta = Path(pasta)
    manifesto = pasta / "manifesto.json"
    if not manifesto.exists():
        return ["manifesto.json ausente"]
    problemas = []
    dados = json.loads(manifesto.read_text(encoding="utf-8"))
    for rel, sha in dados["arquivos"].items():
        f = pasta / rel
        if not f.exists():
            problemas.append(f"{rel}: ausente")
        elif _sha256(f) != sha:
            problemas.append(f"{rel}: SHA-256 diferente do manifesto")
        elif f.suffix == ".db" and (r := integridade(f)) != "ok":
            problemas.append(f"{rel}: integrity_check = {r}")
    return problemas


def restaurar_backup(pasta: Path, data_dir: Path) -> None:
    """Restaura num diretório de dados. Recusa backup com problema e diretório não vazio."""
    pasta, data_dir = Path(pasta), Path(data_dir)
    problemas = verificar_backup(pasta)
    if problemas:
        raise ValueError("backup com problema: " + "; ".join(problemas))
    if data_dir.exists() and any(p for p in data_dir.iterdir() if p.name != "backups"):
        raise ValueError(f"{data_dir} não está vazio; restaure em pasta nova e troque depois")
    data_dir.mkdir(parents=True, exist_ok=True)
    for item in pasta.iterdir():
        if item.name == "manifesto.json":
            continue
        if item.is_dir():
            shutil.copytree(item, data_dir / item.name)
        else:
            shutil.copy2(item, data_dir / item.name)
