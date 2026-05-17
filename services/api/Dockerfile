# Aki control plane (FastAPI). Runs uvicorn behind the Fly proxy.
#
# TODO(infra): This service uses docker.from_env() to spawn one Hermes
# container per org (see app/agent_runtime.py). That works locally because
# the host's /var/run/docker.sock is mounted into the dev container, but
# Fly Machines does NOT expose a Docker daemon to apps. Before this image
# can run on Fly, the spawn path must be swapped to the Fly Machines API
# (or the API must be hosted somewhere with docker.sock available, e.g.
# Railway / a small EC2). See infra/README.md for the two paths forward.
# Owner: backend agent. Do not patch from infra lane.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# git: a few transitive deps install from git+https URLs.
# curl: used by the in-container healthcheck.
# build-essential + libpq-dev: psycopg2-binary ships wheels, but greenlet/
#   uvloop/pgvector can fall back to source builds on slim. Cheap insurance.
# tini: PID 1, reaps zombies (Hermes spawns subprocesses via SDK).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tini \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. UID 10001 to stay clear of any host UID mapping surprises.
RUN groupadd --system --gid 10001 aki \
    && useradd --system --uid 10001 --gid aki --home-dir /app --shell /sbin/nologin aki

WORKDIR /app

# Install deps first for layer caching.
COPY --chown=aki:aki services/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App source. Alembic config + migrations ship in the image so the
# GHA pre-deploy step can run `alembic upgrade head` from this same image.
COPY --chown=aki:aki services/api/app /app/app
COPY --chown=aki:aki services/api/alembic /app/alembic
COPY --chown=aki:aki services/api/alembic.ini /app/alembic.ini

USER aki

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
