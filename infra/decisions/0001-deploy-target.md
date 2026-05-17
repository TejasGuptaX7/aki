# 0001 — Deploy target for `services/api`: Path B (single host with docker.sock)

**Status:** Accepted, 2026-05-17
**Decision-makers:** Founder + backend lane

## Context

`services/api/app/agent_runtime.py` uses `docker.from_env()` to spawn one
per-org Hermes container on demand. This works on any host that exposes
a Docker daemon to the process — a developer Mac, a Linux VM, Railway,
DigitalOcean Apps with the docker addon, EC2 with docker installed, etc.

It does **not** work on Fly Machines: Fly's apps run inside Firecracker
microVMs that don't expose a Docker daemon. To run on Fly Machines, the
control plane would need to call Fly's Machines API to provision per-org
machines instead of spawning Docker containers locally.

Agent C (deploy lane) flagged this in `infra/README.md` and asked which
path the backend takes:

- **Path A**: Migrate `agent_runtime.py` to a Fly Machines API client.
  Real horizontal scaling, multi-region, every per-org workload is its
  own microVM. ~2 hours of refactor + ongoing maintenance of a second
  spawn backend.
- **Path B**: Keep `docker.from_env()`. Deploy `services/api` on a
  single VM (Railway, Hetzner, EC2, DigitalOcean) that has docker.sock
  available. No backend code change.

## Decision

**Path B for v1.** Concretely:

- `services/api` deploys to **a single VM with Docker installed**. First
  prod target is whichever of Railway / Hetzner / DigitalOcean the
  founder picks — all three support a single-host with docker.sock.
- Per-org Hermes containers spawn on that same host via `docker.from_env()`.
- `services/browser-harness` deploys to Fly Machines independently (it
  doesn't need to spawn anything — it IS the spawned workload).
- `apps/web` deploys to Vercel via their GitHub integration.

## Why

1. **Time-to-launch beats cloud-native architecture for an MVP.** Path A
   is well-defined and reversible later. Path B ships now.
2. **Per-org containers stay on one host until per-org density justifies
   horizontal scaling.** A modest 8-vCPU / 32GB VM holds ~50–100 warm
   Hermes profiles with hibernation. That's 50–100 paying customers
   before we hit the ceiling — enough runway to validate the product
   before optimizing for it.
3. **One spawn backend = one set of failure modes to debug.** Two
   backends doubles the surface area when something goes wrong at 2am.
4. **gVisor still works on a single VM.** The Path B host can run
   `runsc` as the Docker runtime, preserving the "each org runs in a
   kernel-isolated sandbox" security story we sell from the trust page.

## What this defers

Triggers that flip us to Path A (Fly Machines API client, multi-region):

- Sustained per-org container count above ~100 active
- Customer with hard data-residency requirement (per-region orgs)
- Real SLA-backed regional uptime claim
- VM cost crosses ~50% of Fly Machines equivalent

When any of those land, the migration is mechanical:

1. Wrap the two `docker.from_env()` call sites in an interface
   (`AgentSpawnBackend`) with `docker_spawn(...)` and `fly_spawn(...)`.
2. Implement `fly_spawn` via the Fly Machines REST API
   (`POST /v1/apps/{app}/machines`).
3. Add a runtime selector: `AGENT_RUNTIME=docker | fly_machines`
   (settings field already exists, currently unused — see `app/config.py`).
4. Per-org workspace mount changes from a host volume to a Fly volume.

Estimated effort when triggered: 1–2 days for the swap + 1 week of
operational shakeout.

## Consequences

- `infra/fly/api.toml` and the `api-deploy.yml` GHA from Agent C's lane
  are not used in v1 (they assume Fly target). Keep them on the
  `deploy-infra` branch as the "when we move to Fly" starting point;
  don't merge to `main` until we actually deploy on Fly.
- The first prod deploy uses a hand-written `docker-compose.yml` at the
  repo root (or per-host setup script) — not Fly. Founder picks the
  host; a follow-up commit adds the compose file.
- Single-VM means the host is a SPOF. Acceptable for a free beta. Pre-
  launch we add: hourly Postgres backups (already in scope), automated
  daily VM snapshots (host-vendor feature), and a 30-minute restore
  playbook documented in `infra/runbooks/`.
