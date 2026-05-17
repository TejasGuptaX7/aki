# Fly-targeted wrapper image for services/api.
#
# Why a wrapper instead of services/api/Dockerfile directly:
#   ADR-0001 picked Path B (single host with docker.sock) for per-org Hermes
#   spawning. On Fly that means we run dockerd *inside* the same Machine as
#   uvicorn — a sidecar process, not a sidecar container — so the api can
#   call docker.from_env() against unix:///var/run/docker.sock with no code
#   change. This Dockerfile layers dockerd on top of the existing api image
#   without polluting the slim image developers run locally.
#
# Build context: repository root.
#   docker build -f infra/fly/api/Dockerfile -t aki-api:fly .
#
# Runtime expectations (see infra/fly/api.toml + infra/DEPLOY.md):
#   - Machine started with privileged=true (Fly Machines API; flag is not
#     in fly.toml — see DEPLOY.md "Privileged mode").
#   - /var/lib/aki mounted from a Fly volume; dockerd state lives under
#     /var/lib/aki/docker, per-org Hermes workspaces under /var/lib/aki/hermes.

# Build stage: reuse the canonical api image so the python deps stay in
# lockstep with what we ship from the lane that owns services/api.
FROM python:3.12-slim AS api-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tini \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/api/app /app/app
COPY services/api/alembic /app/alembic
COPY services/api/alembic.ini /app/alembic.ini


# Final stage: same base, plus dockerd + CLI + iptables (dockerd needs it
# to set up the per-container bridge network even when we don't expose
# Hermes ports outside the Machine).
FROM api-base AS fly

# Docker apt repo — pinned to the bookworm channel so the package set
# matches python:3.12-slim's debian base.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg \
        lsb-release \
        iptables \
        uidmap \
        fuse-overlayfs \
        supervisor \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
         | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
       https://download.docker.com/linux/debian bookworm stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        docker-ce \
        docker-ce-cli \
        containerd.io \
    && rm -rf /var/lib/apt/lists/*

# dockerd writes its state under /var/lib/docker by default; we symlink it
# to the Fly-mounted volume so images + container layers survive Machine
# restarts (a cold docker pull of aki-hermes is ~30s per org otherwise).
RUN mkdir -p /var/lib/aki/docker /var/lib/aki/hermes \
    && rm -rf /var/lib/docker \
    && ln -s /var/lib/aki/docker /var/lib/docker

COPY infra/fly/api/entrypoint.sh /usr/local/bin/aki-entrypoint
RUN chmod +x /usr/local/bin/aki-entrypoint

# We deliberately run as root here. Path B requires uvicorn to share
# /var/run/docker.sock with dockerd, and dropping to a non-root user
# would need careful group plumbing inside a privileged Machine.
# Trade-off documented in ADR-0002.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/aki-entrypoint"]
