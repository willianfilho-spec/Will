# NÃO testado neste ambiente (sem Docker): revise e teste antes de usar em produção.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . .
RUN mkdir -p /dados && chown app:app /dados
USER app
# Dados (SQLite + arquivos) em /dados: monte um volume/disco PERSISTENTE aqui. Sem isso, tudo some ao reiniciar.
ENV CONCILIADOR_DATA_DIR=/dados
# Só confie nos cabeçalhos do proxy se o contêiner só for alcançável pelo proxy da plataforma.
ENV FORWARDED_ALLOW_IPS=*
EXPOSE 8000
# Variáveis a definir na plataforma (nunca na imagem): CONCILIADOR_CHAVE, CONCILIADOR_ADMIN_EMAIL, CONCILIADOR_ADMIN_SENHA
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/saude' % os.environ.get('PORT','8000'),timeout=4)"
CMD ["python", "scripts/rodar_web.py", "--host", "0.0.0.0", "--atras-de-proxy"]
