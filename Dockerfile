FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

RUN adduser --disabled-password appuser
USER appuser

# Cloud Run injects $PORT (default 8080) — never hardcode the port
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
