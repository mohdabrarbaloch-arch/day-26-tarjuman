# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for psycopg, then drop them in the same layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only what the build needs, so the dependency layer caches.
COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --upgrade pip && pip install ".[postgres]"

# Non-root. The app never needs to write outside /app/data.
RUN useradd --create-home --uid 10001 tarjuman \
    && mkdir -p /app/data \
    && chown -R tarjuman:tarjuman /app
USER tarjuman

ENV DATABASE_URL=sqlite:////app/data/tarjuman.db \
    APP_ENV=production \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 2"]
