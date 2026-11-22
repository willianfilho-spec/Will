#!/usr/bin/env bash
# Prepara um servidor Linux (Ubuntu ou Debian) para o Conciliador.
# Rode como usuário com sudo, dentro da pasta automacao-contabil/implantacao.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "[1/5] Instalando o Docker (script oficial em get.docker.com)..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
  echo "Docker instalado. Saia e entre de novo no servidor e rode este script outra vez."
  exit 0
fi
echo "[1/5] Docker: $(docker --version)"

echo "[2/5] Pastas de dados, backup e configuração (dono: uid 1000, o usuário do contêiner)"
mkdir -p dados backups config
sudo chown -R 1000:1000 dados backups config
sudo chmod 700 dados backups config
sudo timedatectl set-timezone America/Fortaleza 2>/dev/null || true

echo "[3/5] Arquivo .env (token do túnel)"
if [ ! -f .env ]; then
  cp .env.exemplo .env
  chmod 600 .env
  read -r -p "Cole o token do túnel da Cloudflare: " TOKEN
  TOKEN="${TOKEN##*install }"; TOKEN="${TOKEN##*--token }"; TOKEN="$(echo "$TOKEN" | tr -d '[:space:]')"
  sed -i "s|^TUNNEL_TOKEN=.*|TUNNEL_TOKEN=${TOKEN}|" .env
fi

echo "[4/5] Imagem do sistema e testes automáticos"
docker compose build app
docker compose run --rm --no-deps -e MOTOR_CONTABIL_ACESSO= app python -m pytest -q -p no:cacheprovider

echo "[5/5] Login Google (quem pode entrar)"
if ! sudo test -f config/acesso.json; then
  sudo install -o 1000 -g 1000 -m 600 acesso.exemplo.json config/acesso.json
fi
docker run --rm -it -v "$PWD/config:/config" conciliador-fortes:fase1 \
  python -m motor_contabil.acesso configurar /config/acesso.json

echo
echo "Pronto. Suba o sistema com:  docker compose up -d"
echo "Acompanhe com:               docker compose ps   e   docker compose logs -f"
