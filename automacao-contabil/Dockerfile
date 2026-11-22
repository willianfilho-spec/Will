# Conciliador Fortes: imagem para servidor (equipe do escritório, login Google
# pelo Cloudflare Access). Funciona em x86-64 e em Arm (ex.: Ampere).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Fortaleza \
    MOTOR_CONTABIL_DADOS=/dados \
    MOTOR_CONTABIL_BACKUP=/backups \
    MOTOR_CONTABIL_ACESSO=/config/acesso.json \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 conciliador

WORKDIR /app
COPY requirements.txt .
# Sem o SDK de IA: no servidor a sugestão por IA fica desligada.
RUN grep -v -i "^anthropic" requirements.txt > req.txt && pip install -r req.txt && rm req.txt

COPY --chown=conciliador:conciliador . .
RUN mkdir -p /dados /backups /config && chown conciliador:conciliador /dados /backups /config
USER conciliador

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py"]
