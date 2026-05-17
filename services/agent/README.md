# services/agent — per-org Hermes container

One Docker container per organization, with multiple Hermes profiles inside
(one per agent). A small Python supervisor (`supervisor.py`) runs as PID 1,
manages the profile subprocesses, and proxies `/v1/*` requests to the
right profile based on the `X-Aki-Agent-Id` header.

Pinned to `hermes-agent==0.13.0` from PyPI.

## Topology

```
                     ┌─────── one Docker container per org ────────┐
                     │                                              │
browser ──► services/api ──► supervisor.py (:8080)                  │
                     │         ├─ /v1/* proxied by X-Aki-Agent-Id   │
                     │         └─ /control/{health,reload}          │
                     │                                              │
                     │       hermes -p <agent-uuid> gateway run     │
                     │         (one process per agent, internal     │
                     │          ports 9001-9100, isolated MEMORY/   │
                     │          USER/sessions per profile)          │
                     │                                              │
                     └──────────────────────────────────────────────┘
```

See `docs/architecture.md` §5 for the runtime model and §6 for how
connections become per-agent MCP servers.

## What lives here

- `Dockerfile` — image definition (`aki-hermes:0.13.0`, Python 3.12 base)
- `supervisor.py` — PID-1 process that manages profiles and proxies requests

What does **not** live here:

- Per-org state, secrets, manifest, per-agent config — written by the
  control plane (`services/api/app/agent_runtime.py`) into the mounted
  volume at `/opt/data/`
- Tool catalogues / OAuth tokens — those live in Composio / Pipedream and
  surface to Hermes via MCP

## Local dev

```bash
# from repo root
docker build -t aki-hermes:0.13.0 services/agent
# the control plane launches containers; running by hand is for debugging only
```

To exercise end-to-end, run uvicorn against the API and let it `docker run`
the container for a real org. See `services/api/README.md` for that path.
