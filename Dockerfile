FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend.py index.html ./

ENV PYTHONUNBUFFERED=1 \
    DEFAULT_DATA_DIR=/app/data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"]
