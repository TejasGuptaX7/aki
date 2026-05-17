# 0002 — Run Path B on Fly via sidecar dockerd

**Status:** Accepted, 2026-05-17
**Decision-makers:** Founder + infra lane
**Supersedes:** the "do not merge fly/api.toml to main" caveat in
[`0001-deploy-target.md`](0001-deploy-target.md) §Consequences. Path B is
still the chosen spawn strategy; what changes is the host.

## Context

[ADR-0001](0001-deploy-target.md) picked Path B (`services/api` runs on a
single VM with `/var/run/docker.sock` available) and explicitly listed
Railway / Hetzner / EC2 as host candidates because **"Fly Machines does
not expose a Docker daemon to apps."** It deferred the Fly target.

Operational reality two weeks later:

- We already deploy `services/browser-harness` on Fly Machines and the
  ergonomics (per-region pinning, 6PN internal DNS, secrets, logs) are
  the best of the candidates.
- Running the api on a second platform (Railway) means two log dashboards,
  two billing accounts, two CI quirks, two secret stores.
- Fly Machines *do* support privileged guests (with org-level approval).
  A privileged Machine can run dockerd as a sidecar process inside the
  same VM as uvicorn, exposing `/var/run/docker.sock` to the api with
  zero code change. This was not obvious from the Fly docs in May; it
  became clear after a support ticket.

## Decision

**Run Path B on Fly. `services/api` ships as a single Fly Machine that
boots dockerd in the background before exec'ing uvicorn.**

Concretely:

- `infra/fly/api/Dockerfile` wraps the canonical `services/api` image and
  adds `docker-ce`, `docker-ce-cli`, `containerd.io`, `iptables`, and a
  small `entrypoint.sh` that starts dockerd → waits for the socket →
  exec's uvicorn.
- `infra/fly/api.toml` declares one Machine in `iad`, `performance-2x`
  (2 vCPU / 4 GB), with `/var/lib/aki` mounted from a 50 GB Fly volume.
  dockerd state (`/var/lib/aki/docker`) and per-org workspace dirs
  (`/var/lib/aki/hermes`) both live on that volume.
- `infra/fly-deploy.sh` flips each api Machine to `privileged = true`
  via the Fly Machines REST API after deploy. fly.toml has no field for
  this today.
- Postgres = Neon (unchanged). Redis = Upstash for Redis on Fly,
  attached via `fly redis attach` so `REDIS_URL` lands as a secret.
- `services/api/app/agent_runtime.py` keeps `docker.from_env()`. No
  code change.

## Why this beats the alternatives

| Option                                                | Why we passed                                                                 |
| ----------------------------------------------------- | ----------------------------------------------------------------------------- |
| Fly Machines API spawn (Path A from ADR-0001)         | ~2 days of backend work + ongoing maintenance of a second spawn backend. Defers value. |
| Railway single VM                                     | Two platforms, two log dashboards, no 6PN; we'd still run `services/browser-harness` on Fly. |
| Hetzner CX32 + docker-compose                         | Cheapest, but ops overhead (OS patching, our own TLS termination, our own metrics scrape). Saved as the rollback path if Fly denies privileged. |
| EC2 + docker-compose                                  | Same as Hetzner but more expensive.                                           |

## Known limitations

1. **Privileged Machines are an org-level approval.** New Fly orgs need
   to email support to enable; turnaround is typically same-day. The
   deploy script's `privileged` stage 403s otherwise. Documented in
   [`DEPLOY.md`](../DEPLOY.md#privileged-mode).
2. **Single Machine = single point of failure.** A Machine restart drops
   every live per-org Hermes container (they're in-memory `_REGISTRY`
   state from `agent_runtime.py`). Fly's `auto_start_machines = true` +
   `min_machines_running = 1` recovers in ~30s; orgs cold-start on the
   next chat. Acceptable for free beta.
3. **Volume is single-region.** Fly volumes are region-pinned; we can't
   trivially fail over the api to a second region without losing
   dockerd state (and therefore the warm per-org Hermes containers).
   When per-org density justifies multi-region, we flip to Path A.
4. **Privileged dockerd means the api Machine is the security boundary
   for all orgs.** gVisor isolation (mentioned in ADR-0001 §"Why" #4)
   is deferred — switching dockerd to `runsc` inside a Fly Machine
   needs more testing. Tracked.

## Rollback

If Fly denies privileged or we hit a hard scaling wall:

1. Provision a Hetzner CX32 (or DigitalOcean Droplet) with docker +
   docker-compose preinstalled.
2. Run `services/api/Dockerfile` directly (no wrapper needed; the host
   has docker natively).
3. Point Cloudflare DNS at the new host's IP, swap the certificate.
4. Keep `services/browser-harness` on Fly — it doesn't change.

Estimated cutover: half a day, including DNS propagation.

## What this changes from ADR-0001

- `infra/fly/api.toml` is no longer "do not merge until we deploy on
  Fly." It's the production config.
- The `FLY_API_TOKEN` secret on the api Fly app from ADR-0001 §Open
  question is no longer needed (no Machines API client). Kept in the
  GHA repo secret list for `flyctl deploy` only.
- `agent_runtime` field in `Settings` stays unused for now. Path B
  doesn't branch on it.

## Triggers to revisit

The triggers in ADR-0001 §"What this defers" still apply. Add one:

- **Fly support removes privileged from our org** (e.g. policy change).
  Rollback path above.
