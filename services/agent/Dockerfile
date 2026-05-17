# Hermes per-org runtime. One image, one container per org, multiple
# Hermes profiles inside (one per agent), managed by supervisor.py.
#
# Note: docs/architecture.md targets sub-version v0.4.0 but Nous publishes a
# different version line to PyPI (calver-ish, currently 0.13.0). For now we
# track the latest published wheel; revisit pinning when Nous stabilizes the
# PyPI line.
#
# Differs from Nous's official Dockerfile:
#   - pip install (not source build) — no TUI, no Playwright, no web dashboard
#   - supervisor.py (this repo) sits in front of N hermes profiles, one per
#     agent, and proxies /v1/* by X-Aki-Agent-Id header
#   - control plane handles per-org workspace mount + manifest authoring
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
#   - aiohttp for the OpenAI-compatible API server AND the supervisor proxy
RUN pip install \
        "hermes-agent==${HERMES_VERSION}" \
        "mcp>=1.6.0" \
        "aiohttp>=3.9"

# Per-org workspace mount. Control plane mounts
# ${HERMES_DATA_DIR}/<org_id>/ here at container start. Per-agent
# Hermes profiles live under /opt/data/agents/<agent_id>/.
WORKDIR /opt/data
VOLUME ["/opt/data"]

# Supervisor sits at /opt/supervisor.py so it survives `HERMES_HOME=/opt/data`
# being a volume mount (anything under /opt/data is overwritten at runtime).
COPY supervisor.py /opt/supervisor.py

# Defaults overridden by the control plane at `docker run` time per-org:
#   SUPERVISOR_API_KEY  (required; control plane supplies a fresh secret)
#   PROFILE_PORT_LOW / PROFILE_PORT_HIGH (defaults baked into supervisor.py)
ENV SUPERVISOR_HOST=0.0.0.0 \
    SUPERVISOR_PORT=8080

EXPOSE 8080

# tini reaps zombie children from hermes profile subprocesses and forwards
# SIGTERM cleanly so `docker stop` runs the supervisor's shutdown handler
# which in turn SIGTERMs all hermes profiles before exit.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/opt/supervisor.py"]
