FROM python:3.13-slim

WORKDIR /app

# Минимум пакетов для API без OCR (без libgl/torch). Для полного стека смотрите optional [ocr].
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    build-essential \
    gcc \
    g++ \
    make \
    pkg-config \
    python3-dev \
    libssl-dev \
    p7zip-full \
    libarchive-tools \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Обновляем сертификаты
RUN update-ca-certificates

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
# Ядро API: без группы dev и без optional [ocr] (YOLO, Ollama, ocrmypdf, OpenCV, …).
# Локально с OCR: uv sync --extra ocr --group dev
# После правок зависимостей обновите lock: uv lock
RUN uv sync --no-dev

COPY . .

RUN sed -i 's/\r$//' /app/backend/entrypoint.sh && chmod +x /app/backend/entrypoint.sh

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["sh", "-c", "sed -i 's/\\r$//' /app/backend/entrypoint.sh && /app/backend/entrypoint.sh"]