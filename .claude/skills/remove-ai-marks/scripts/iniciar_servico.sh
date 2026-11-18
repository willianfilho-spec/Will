#!/usr/bin/env bash
# Sobe o serviço local em segundo plano, se ainda não estiver no ar, e espera o /health.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTA="${WATERMARKS_SERVICE_PORT:-8765}"
WM="http://127.0.0.1:${PORTA}"
LOG="${TMPDIR:-/tmp}/remove-ai-marks-servico.log"

AUTH=()
if [ -n "${WATERMARKS_SERVER_API_KEY:-}" ]; then
  AUTH=(-H "Authorization: Bearer ${WATERMARKS_SERVER_API_KEY}")
fi

no_ar() { curl -sf -m 2 "${AUTH[@]}" "${WM}/health" >/dev/null 2>&1; }

if no_ar; then
  echo "Serviço já está no ar em ${WM}"
  exit 0
fi

nohup python3 "${AQUI}/servico.py" --port "${PORTA}" >"${LOG}" 2>&1 &
PID=$!

for _ in $(seq 1 25); do
  if no_ar; then
    echo "Serviço no ar em ${WM} (pid ${PID}, log em ${LOG})"
    exit 0
  fi
  if ! kill -0 "${PID}" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

echo "Falha ao subir o serviço. Log:" >&2
cat "${LOG}" >&2 || true
exit 1
