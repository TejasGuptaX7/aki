# Hermes per-org runtime. One image, one process per org, hibernates idle.
# Built off the official Hermes Agent base; pinned to v0.4.0 per
# docs/architecture.md §4.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_VERSION=0.4.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gettext-base \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "hermes-agent==${HERMES_VERSION}"

# Per-org workspace mount point. The control plane mounts
# ${HERMES_DATA_DIR}/<org_id>/ here at container start.
WORKDIR /workspace
VOLUME ["/workspace"]

COPY hermes.config.yaml /etc/hermes/hermes.config.yaml.tpl

EXPOSE 8080

# Entry: render the template with env, then start the gateway.
CMD ["sh", "-c", "envsubst < /etc/hermes/hermes.config.yaml.tpl > /workspace/hermes.config.yaml && hermes gateway --config /workspace/hermes.config.yaml"]
