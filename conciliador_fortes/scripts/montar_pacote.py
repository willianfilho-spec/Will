"""Monta o pacote de teste para Windows (zip com Python embutido, sem instalação).

    python scripts/montar_pacote.py [--cache PASTA] [--saida PASTA]

Precisa de internet só nesta etapa (PyPI e NuGet). O pacote final roda offline.
Resultado: Conciliador-MVP-AAAAMMDD.zip, com
    python/   Python 3.12 para Windows (pacote `python` do NuGet) com as dependências já dentro
    app/      o código do Conciliador
    INICIAR.bat, LEIA-ME.txt, ROTEIRO_DE_TESTE.txt, ... e "Arquivos de exemplo"
Não inclui dados, chaves nem nada de cliente. O zip NÃO deve ir para o git (veja .gitignore).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY_VERSAO = "3.12.8"
NUPKG_URL = f"https://api.nuget.org/v3-flatcontainer/python/{PY_VERSAO}/python.{PY_VERSAO}.nupkg"
DEPENDENCIAS = ["fastapi", "uvicorn", "jinja2", "python-multipart", "cryptography", "openpyxl", "colorama"]
CODIGO = ["config.py", "web", "domain", "storage", "parsers", "exporters", "ai", "exemplos"]
SCRIPTS = ["iniciar_mvp.py", "scripts_demo.py", "teste_restauracao.py", "gerar_lote_homologacao.py",
           "validar_lote_existente.py"]
DESCARTAR_DO_PYTHON = ("Lib/test/", "Lib/idlelib/", "Lib/turtledemo/", "Lib/tkinter/", "Lib/lib2to3/", "tcl/",
                       "Doc/", "include/", "libs/")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def baixar(cache: Path) -> tuple[Path, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    nupkg, rodas = cache / f"python.{PY_VERSAO}.nupkg", cache / "wheels"
    if not nupkg.exists():
        print(f"Baixando Python {PY_VERSAO} para Windows...")
        urllib.request.urlretrieve(NUPKG_URL, nupkg)
    if not rodas.exists() or not any(rodas.iterdir()):
        print("Baixando dependências compiladas para Windows (cp312, win_amd64)...")
        subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--platform", "win_amd64", "--python-version",
                        "3.12", "--implementation", "cp", "--only-binary=:all:", "-d", str(rodas), *DEPENDENCIAS], check=True)
    return nupkg, rodas


def commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, capture_output=True, text=True).stdout.strip() or "?"
    except OSError:
        return "?"


def montar(cache: Path, saida: Path) -> Path:
    nupkg, rodas = baixar(cache)
    nome = f"Conciliador-MVP-{date.today():%Y%m%d}"
    pasta = saida / nome
    if pasta.exists():
        shutil.rmtree(pasta)
    (pasta / "python").mkdir(parents=True)
    # 1) Python
    with zipfile.ZipFile(nupkg) as z:
        for m in z.namelist():
            if not m.startswith("tools/") or m.endswith("/"):
                continue
            rel = m[len("tools/"):]
            if rel.startswith(DESCARTAR_DO_PYTHON) or rel.startswith("Scripts/") or "__pycache__" in rel:
                continue
            destino = pasta / "python" / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(z.read(m))
    # 2) dependências: uma roda é um zip; extrair em site-packages equivale a instalar
    site = pasta / "python" / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for r in sorted(rodas.glob("*.whl")):
        with zipfile.ZipFile(r) as z:
            z.extractall(site)
    # 3) código
    app = pasta / "app"
    ignorar = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.key", "data", "dados")
    for item in CODIGO:
        origem = RAIZ / item
        if origem.is_dir():
            shutil.copytree(origem, app / item, ignore=ignorar)
        else:
            (app).mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, app / item)
    (app / "scripts").mkdir(exist_ok=True)
    for s in SCRIPTS:
        shutil.copy2(RAIZ / "scripts" / s, app / "scripts" / s)
    # 4) arquivos para a pessoa que vai testar
    for f in (RAIZ / "empacotar").iterdir():
        shutil.copy2(f, pasta / f.name)
    shutil.copytree(RAIZ / "exemplos", pasta / "Arquivos de exemplo", ignore=ignorar)
    versoes = "\n".join(f"  {r.name}  sha256 {sha(r)[:16]}" for r in sorted(rodas.glob("*.whl")))
    (pasta / "VERSAO.txt").write_text(
        f"Conciliador MVP de teste\nMontado em {date.today():%d/%m/%Y} a partir do commit {commit()}\n"
        f"Python {PY_VERSAO} (NuGet) sha256 {sha(nupkg)[:16]}\nDependências:\n{versoes}\n", encoding="utf-8")
    # 5) zip
    destino = saida / f"{nome}.zip"
    if destino.exists():
        destino.unlink()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(pasta.rglob("*")):
            if f.is_file():
                z.write(f, Path(nome) / f.relative_to(pasta))
    return destino


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=RAIZ / "dist" / "cache")
    ap.add_argument("--saida", type=Path, default=RAIZ / "dist")
    a = ap.parse_args()
    z = montar(a.cache, a.saida)
    print(f"\nPacote: {z}  ({z.stat().st_size / 1e6:.1f} MB)\nSHA-256: {sha(z)}")
