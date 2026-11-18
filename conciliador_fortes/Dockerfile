# NÃO testado neste ambiente (sem Docker). Revise antes de usar.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app
ENV CONCILIADOR_DATA_DIR=/dados
VOLUME ["/dados"]
EXPOSE 8000
# a chave vem de CONCILIADOR_CHAVE (defina no ambiente; nunca na imagem)
CMD ["python", "scripts/rodar_web.py", "--host", "0.0.0.0", "--port", "8000", "--atras-de-proxy"]
