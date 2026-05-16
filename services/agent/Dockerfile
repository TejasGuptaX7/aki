# Hermes per-org runtime. One image, one process per org, hibernates idle.
#
# Note: docs/architecture.md targets sub-version v0.4.0 but Nous publishes a
# different version line to PyPI (calver-ish, currently 0.13.0). For now we
# track the latest published wheel; revisit pinning when Nous stabilizes the
# PyPI line.
#
# Differs from Nous's official Dockerfile:
#   - pip install (not source build) — no TUI, no Playwright, no web dashboard
#   - we only need the gateway (OpenAI-compatible API server) + MCP
#   - control plane handles per-org workspace mount + config materialization
#
# If we ever need browser tools or the TUI, switch to building from
# github.com/NousResearch/hermes-agent's Dockerfile instead.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_VERSION=0.13.0 \
    HERMES_HOME=/opt/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gettext-base tini \
    && rm -rf /var/lib/apt/lists/*

# hermes-agent + extras the gateway needs at runtime that aren't hard deps:
#   - mcp >=1.6 for streamable HTTP transport (composio MCP)
#   - aiohttp for the OpenAI-compatible API server
RUN pip install \
        "hermes-agent==${HERMES_VERSION}" \
        "mcp>=1.6.0" \
        "aiohttp>=3.9"

# Per-org workspace mount. Control plane mounts
# ${HERMES_DATA_DIR}/<org_id>/ here at container start.
WORKDIR /opt/data
VOLUME ["/opt/data"]

COPY hermes.config.yaml /etc/hermes/hermes.config.yaml.tpl

# The OpenAI-compatible API server is OFF unless these are set. Our
# control plane proxies to it, so it MUST be on.
ENV API_SERVER_HOST=0.0.0.0 \
    API_SERVER_PORT=8080
# API_SERVER_KEY is provided at `docker run` time per-org so each container
# has a unique key for the control plane proxy to send.

EXPOSE 8080

# tini reaps zombie children from MCP stdio subprocesses.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "envsubst < /etc/hermes/hermes.config.yaml.tpl > /opt/data/hermes.config.yaml && hermes gateway --config /opt/data/hermes.config.yaml"]
