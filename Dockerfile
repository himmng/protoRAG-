FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) CF_ARCH=amd64 ;; \
         arm64) CF_ARCH=arm64 ;; \
         *) echo "unsupported arch: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL -o /usr/local/bin/cloudflared \
         "https://github.com/cloudflare/cloudflared/releases/download/2024.12.2/cloudflared-linux-${CF_ARCH}" \
    && chmod +x /usr/local/bin/cloudflared \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser \
    && mkdir -p /app/data && chown appuser:appuser /app/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY index.html ./
COPY static ./static
COPY entrypoint.sh ./
RUN chmod +x ./entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    DEFAULT_DATA_DIR=/app/data \
    SERVE_FRONTEND=true \
    PROTORAG_DEFAULT_PROVIDER=ollama \
    PROTORAG_DEFAULT_BASE_URL=http://host.docker.internal:11434

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

USER appuser

ENTRYPOINT ["./entrypoint.sh"]
