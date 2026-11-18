"""Inicia o Conciliador (MVP de teste) NESTE computador. Roda no navegador, sem internet e sem instalar nada.

    python scripts/iniciar_mvp.py [--pasta-dados PASTA] [--rede] [--sem-navegador]

- Na primeira vez cria dados de demonstração (empresa fictícia e quatro usuários de teste).
- Os dados ficam na pasta `dados` ao lado do programa. Apagar essa pasta volta tudo ao início.
- Por padrão só este computador acessa (127.0.0.1). Com --rede, outros computadores da MESMA rede
  podem abrir o endereço mostrado. Não há HTTPS: use só em rede interna e com dados de teste.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
EMPACOTADO = (RAIZ.parent / "python").exists()  # pacote final: app/ ao lado de python/ e dados/


def _utf8() -> None:
    """O console do Windows usa uma página de código antiga; sem isto, acentos podem derrubar o programa."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _porta_livre(host: str, inicio: int = 8000, fim: int = 8020) -> int:
    for p in range(inicio, fim + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise SystemExit(f"As portas {inicio} a {fim} estão ocupadas. Feche outros programas e tente de novo.")


def _ip_da_rede() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "IP-DESTE-COMPUTADOR"


def _abrir_quando_pronto(url: str, porta: int) -> None:
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.2)


def main() -> None:
    _utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pasta-dados", type=Path, default=(RAIZ.parent / "dados") if EMPACOTADO else (RAIZ / "data_mvp"))
    ap.add_argument("--rede", action="store_true", help="permite acesso de outros computadores da mesma rede")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--porta", type=int)
    a = ap.parse_args()

    pasta = a.pasta_dados.resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    # Modo de teste local: cookie sem Secure (não há HTTPS), sem 2FA, arquivos cifrados com chave em dados/chave.key.
    os.environ.update(CONCILIADOR_DATA_DIR=str(pasta), CONCILIADOR_HTTP_LOCAL="1", CONCILIADOR_EXIGIR_2FA="0",
                      CONCILIADOR_CRIPTO="1")
    sys.path.insert(0, str(RAIZ))
    sys.path.insert(0, str(RAIZ / "scripts"))

    import uvicorn

    from scripts_demo import SENHA, criar_demo
    from web.app import criar_app

    primeira_vez = not (pasta / "central.db").exists()
    if primeira_vez:
        print("Primeira execução: criando dados de demonstração...")
        criar_demo(pasta)
    host = "0.0.0.0" if a.rede else "127.0.0.1"
    porta = a.porta or _porta_livre(host)
    url = f"http://127.0.0.1:{porta}"
    print("\n" + "=" * 66)
    print(" CONCILIADOR - versão de teste (MVP)")
    print("=" * 66)
    print(f" Abra no navegador:  {url}")
    if a.rede:
        print(f" Outros computadores da rede:  http://{_ip_da_rede()}:{porta}")
        print(" ATENÇÃO: sem HTTPS. Use só em rede interna e com dados de teste.")
    print(f"\n Usuários de teste (senha de todos: {SENHA}):")
    print("   admin@demo.test      administrador")
    print("   operador@demo.test   equipe: carrega e classifica")
    print("   revisor@demo.test    equipe: confirma e gera o lote")
    print("   cliente@demo.test    cliente: envia arquivos")
    print(f"\n Dados guardados em: {pasta}")
    print(" Para encerrar: feche esta janela (ou CTRL+C).")
    print("=" * 66 + "\n")
    if not a.sem_navegador:
        threading.Thread(target=_abrir_quando_pronto, args=(url, porta), daemon=True).start()
    app = criar_app(pasta, dica_login=(
        f"Modo de teste. Entre com operador@demo.test, revisor@demo.test, cliente@demo.test ou admin@demo.test. "
        f"Senha: {SENHA}"))
    uvicorn.run(app, host=host, port=porta, log_level="warning", access_log=False, server_header=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEncerrado.")
