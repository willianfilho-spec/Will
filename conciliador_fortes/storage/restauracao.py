"""Teste de restauração em ambiente isolado (evidência do item H4).

Faz um backup da pasta de dados, restaura numa pasta temporária nova e compara
a cópia com a origem: tabelas e contagens de linhas, integrity_check, SHA-256
dos arquivos originais e dos lotes. A pasta de dados de origem só é lida.
"""

from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from domain.deduplicator import sha256
from storage.backup import criar_backup, integridade, restaurar_backup, verificar_backup

VERSAO = 1


def _apagar(pasta: Path) -> None:
    """rmtree que também remove arquivos somente leitura (necessário no Windows)."""
    import os
    import stat

    def liberar(func, caminho, _exc):
        os.chmod(caminho, stat.S_IWRITE)
        func(caminho)

    shutil.rmtree(pasta, onerror=liberar)


def _contagens(db: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tabelas = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tabelas}
    finally:
        con.close()


def _origem_sintetica(central: Path) -> bool:
    con = sqlite3.connect(f"file:{central}?mode=ro", uri=True)
    try:
        emails = [r[0] for r in con.execute("SELECT email FROM usuarios")]
    finally:
        con.close()
    return bool(emails) and all(e.endswith((".test", ".example", ".invalid")) for e in emails)


def executar(data_dir: Path, manter_pasta: bool = False) -> dict:
    data_dir = Path(data_dir)
    verificacoes: list[dict] = []

    def registrar(teste: str, ok: bool, detalhe: str = "") -> None:
        verificacoes.append({"teste": teste, "resultado": "ok" if ok else "falha", "detalhe": detalhe})

    if not (data_dir / "central.db").exists():
        raise FileNotFoundError(f"{data_dir} não tem central.db")
    tmp = Path(tempfile.mkdtemp(prefix="restauracao_"))
    try:
        pasta_bk = criar_backup(data_dir, tmp / "backup")
        prob = verificar_backup(pasta_bk)
        registrar("backup criado e conferido contra o manifesto", not prob, "; ".join(prob))
        destino = tmp / "restaurado"
        try:
            restaurar_backup(pasta_bk, destino)
            registrar("restauração em pasta isolada", True, "pasta temporária nova")
        except ValueError as exc:
            registrar("restauração em pasta isolada", False, str(exc))
            destino = None
        if destino is not None:
            bancos = [data_dir / "central.db"] + sorted((data_dir / "empresas").glob("*/contabil.db"))
            for db in bancos:
                rel = db.relative_to(data_dir)
                copia = destino / rel
                if not copia.exists():
                    registrar(f"{rel}: presente na restauração", False, "ausente")
                    continue
                r = integridade(copia)
                registrar(f"{rel}: integrity_check", r == "ok", r)
                a, b = _contagens(db), _contagens(copia)
                difs = [f"{t}: {a.get(t)} x {b.get(t)}" for t in sorted(set(a) | set(b)) if a.get(t) != b.get(t)]
                registrar(f"{rel}: tabelas e contagens iguais à origem", not difs,
                          "; ".join(difs) or f"{len(a)} tabelas, {sum(a.values())} linhas")
                if db.name == "contabil.db":
                    con = sqlite3.connect(f"file:{copia}?mode=ro", uri=True)
                    con.row_factory = sqlite3.Row
                    try:
                        ruins = []
                        for tabela in ("arquivos", "lotes"):
                            for row in con.execute(f"SELECT id, caminho, sha256 FROM {tabela}"):
                                f = copia.parent / row["caminho"]
                                if not f.exists() or sha256(f.read_bytes()) != row["sha256"]:
                                    ruins.append(f"{tabela} {row['id']}")
                        n = con.execute("SELECT (SELECT COUNT(*) FROM arquivos) + (SELECT COUNT(*) FROM lotes)").fetchone()[0]
                    finally:
                        con.close()
                    registrar(f"{rel.parent}: arquivos originais e lotes com SHA-256 íntegro", not ruins,
                              "; ".join(ruins) or f"{n} arquivo(s) conferido(s)")
        aprovado = bool(verificacoes) and all(v["resultado"] == "ok" for v in verificacoes)
        return {
            "ferramenta": "teste_restauracao",
            "versao": VERSAO,
            "executado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sistema": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "origem_sintetica": _origem_sintetica(data_dir / "central.db"),
            "pasta_isolada_mantida": str(tmp) if manter_pasta else None,
            "verificacoes": verificacoes,
            "resultado": "aprovado" if aprovado else "reprovado",
        }
    finally:
        if not manter_pasta:
            _apagar(tmp)


def salvar(relatorio: dict, saida: Path) -> None:
    Path(saida).write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
