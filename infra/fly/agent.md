# Why there is no `infra/fly/agent.toml`

The Hermes agent image is **not** deployed as a persistent Fly app. It is a
**per-org spawn target**: one Machine per org, started by the control plane
on first chat, hibernated after `HERMES_IDLE_MINUTES` (default 15) of
inactivity, destroyed on org delete.

Deploying it as a Fly app would either:

- give us one shared agent process for all orgs (defeats per-org isolation,
  per-org config materialization, per-org workspace volume), or
- require N Fly apps for N orgs, which is operationally untenable and hits
  Fly's per-org app limits fast.

## How it actually ships

1. `.github/workflows/agent-image-build.yml` builds
   `services/agent/Dockerfile` and pushes `ghcr.io/akiapp/agent:<sha>` +
   `ghcr.io/akiapp/agent:latest` on every push to `main` that touches
   `services/agent/**`.

2. The control plane (`services/api/app/agent_runtime.py`) spawns one
   Machine per org from that image via the Fly Machines API, attaching a
   per-org volume mounted at `/opt/data`.

3. Hibernation = `machines stop`. Wake = `machines start`. Delete = `machines
   destroy`.

## What the backend agent owes here

`agent_runtime.py` currently calls `docker.from_env()`. That has to be
swapped for `fly_machines.Client(...)` (or an equivalent thin wrapper)
before the API itself runs on Fly. Tracked in `infra/README.md` under
**Open architectural question**.

## What infra owes here

- Reserve the Fly org / region the per-org Machines will land in
  (default: `iad`, same as the control plane, to keep latency low).
- Create one Fly volume template per region (`aki-hermes-data`) — the
  control plane creates concrete volumes per org from that template.
- Make sure the Fly API token in `FLY_API_TOKEN` (set on the control plane
  app as a secret) has `machines:write` + `volumes:write` scopes.
