"""Sobe o web app.

    python scripts/rodar_web.py --demo                       # demonstração local, sem HTTPS, dados de exemplo
    python scripts/rodar_web.py --host 127.0.0.1 --port 8000 # produção (atrás de proxy com HTTPS)

Em produção exige CONCILIADOR_CHAVE. O modo --demo desliga 2FA e cookie Secure e NÃO serve para produção.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--demo", action="store_true")
ap.add_argument("--atras-de-proxy", action="store_true", help="confia nos cabeçalhos do proxy em 127.0.0.1")
a = ap.parse_args()

if a.demo:
    if a.host not in ("127.0.0.1", "localhost"):
        sys.exit("--demo só pode escutar em 127.0.0.1.")
    pasta = Path(tempfile.mkdtemp(prefix="conciliador_demo_"))
    os.environ.update(CONCILIADOR_DATA_DIR=str(pasta), CONCILIADOR_HTTP_LOCAL="1", CONCILIADOR_EXIGIR_2FA="0",
                      CONCILIADOR_CRIPTO="1")
elif not os.environ.get("CONCILIADOR_CHAVE"):
    sys.exit("Defina CONCILIADOR_CHAVE (gere com scripts/gerar_chave.py). Sem ela os arquivos não ficam cifrados.")

sys.path.insert(0, str(RAIZ))
import uvicorn  # noqa: E402

import config  # noqa: E402

if a.demo:
    from scripts_demo import criar_demo  # noqa: E402
    criar_demo(config.DATA_DIR)
    print(f"\nDEMONSTRAÇÃO em http://{a.host}:{a.port}  (dados em {config.DATA_DIR})\n"
          "Senha de todos: Demo-Conciliador-2026!\n"
          "  admin@demo.test · operador@demo.test · revisor@demo.test · cliente@demo.test\n")
from web.app import criar_app  # noqa: E402

uvicorn.run(criar_app(config.DATA_DIR), host=a.host, port=a.port, log_level="info",
            proxy_headers=a.atras_de_proxy, forwarded_allow_ips="127.0.0.1" if a.atras_de_proxy else None,
            server_header=False)
