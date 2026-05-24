# services/agent — Hermes per-org runtime

One Hermes Agent process per organization, pinned to **v0.13.0**.
Receives traffic from the control plane gateway (`services/api`), never from
the browser directly.

## Topology

```
browser ──► services/api gateway ──► services/agent (per-org Hermes)
                       │                       │
                       │                       └─ MCP / Composio / native plugins
                       └─ enforces auth, RBAC, audit before any tool call
```

See `docs/architecture.md` §4 for the design.

## Local dev

```bash
# from repo root
docker build -t aki-agent:0.13.0 services/agent
docker run --rm -p 8080:8080 \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v "$PWD/.local/hermes/dev-org":/workspace \
  aki-agent:0.13.0
```

The control plane materializes one `${HERMES_DATA_DIR}/<org_id>/` directory
per org and mounts it at `/workspace` when starting the container. Memory
files (`MEMORY.md`, `USER.md`) and OAuth tokens persist there between runs.

## What lives here

- `Dockerfile` — image definition (Hermes 0.13.0 base).
- `hermes.config.yaml` — config **template** rendered with `envsubst` at boot.

What does **not** live here: per-org state, secrets, or org-specific tool
registrations. Those come from Postgres at boot time via the sync skill.
