# ──────────────────────────────────────────────────────────────────────────────
# Production Dockerfile for the Hermes API (FastAPI control plane)
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# ── Environment ──
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=prod

# ── System deps ──
#   - libpq-dev + gcc: required to build psycopg2-binary from source if a wheel
#     isn't available for the target architecture.
#   - curl: used by the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ──
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # Gunicorn + Uvicorn worker class for production multi-process serving.
    gunicorn>=23.0

# ── Application code ──
# Copy everything under services/api into /app.  The PYTHONPATH is set below
# so `app.main:app` resolves correctly.
COPY . /app

# ── Non-root user ──
RUN groupadd -r aki && useradd -r -g aki aki \
    && chown -R aki:aki /app
USER aki

# ── Runtime config ──
ENV PYTHONPATH=/app \
    PORT=8000

EXPOSE 8000

# ── Health check ──
# FastAPI health endpoint is mounted at /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# ── Start with Gunicorn + Uvicorn workers ──
#   - 4 workers is a sane default for a 2-core container.
#   - `--preload` imports the app once in the master process, reducing per-worker
#     memory overhead and ensuring import-time errors fail fast on boot.
#   - `--access-logfile -` sends access logs to stdout for container log aggregation.
#   - `--capture-output` forwards worker stdout/stderr to the master log.
#   - `--worker-class uvicorn.workers.UvicornWorker` uses the official ASGI worker.
#   - `--timeout 120` allows long-running requests (streaming chat completions).
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--preload", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--capture-output", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "app.main:app"]
