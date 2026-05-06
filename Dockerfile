FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser \
    && mkdir -p /app/data && chown appuser:appuser /app/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend.py index.html ./

ENV PYTHONUNBUFFERED=1 \
    DEFAULT_DATA_DIR=/app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

USER appuser

CMD ["python", "-m", "uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"]
