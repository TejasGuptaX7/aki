# Aki infra

Everything needed to take Aki from zero to a running production deploy on
Fly + Vercel + Neon + Cloudflare. **Start with [`DEPLOY.md`](DEPLOY.md)** —
this README is the map.

```
infra/
├── README.md              ← you are here
├── DEPLOY.md              ← end-to-end deploy runbook (start here)
├── fly-deploy.sh          ← idempotent deploy script driving the runbook
├── secrets-bootstrap.md   ← every secret name + where its value comes from
├── decisions/
│   ├── 0001-deploy-target.md   ← Path B (single host with docker.sock)
│   └── 0002-fly-with-dind.md   ← Path B on Fly via sidecar dockerd
├── fly/
│   ├── api.toml           ← Fly Machines config for services/api
│   ├── api/
│   │   ├── Dockerfile     ← wraps services/api with dockerd + iptables
│   │   └── entrypoint.sh  ← boots dockerd then exec's uvicorn
│   ├── proxy.toml         ← Fly Machines config for services/browser-harness/proxy
│   └── agent.md           ← why services/agent has no fly.toml (per-org spawn)
└── grafana/
    ├── api.dashboard.json
    ├── agent.dashboard.json
    └── browser-harness.dashboard.json
```

The four services:

| Service                          | Where it runs                                                    | Owned config                                |
| -------------------------------- | ---------------------------------------------------------------- | ------------------------------------------- |
| `services/api`                   | Fly app `aki-api` (single privileged Machine, dockerd sidecar)   | `infra/fly/api.toml` + `infra/fly/api/`     |
| `services/agent` (Hermes)        | Per-org Docker container on the api Machine (Path B)             | GHCR image only — see `fly/agent.md`        |
| `services/browser-harness/proxy` | Fly app `aki-browser-harness` (v2 lean proxy)                    | `infra/fly/proxy.toml`                      |
| `apps/web`                       | Vercel                                                           | `apps/web/vercel.json`                      |

> The older `services/browser-harness/fly.toml` is the v1 chromium-in-image
> harness, owned by the harness lane. v2 (proxy/) is what we deploy now;
> see ADR-0002 for the cutover.

## Architecture in one paragraph

Path B (ADR-0001) + sidecar dockerd on Fly (ADR-0002). The api Machine
boots dockerd in the background before uvicorn starts, so
`docker.from_env()` in `services/api/app/agent_runtime.py` finds a local
socket and per-org Hermes containers spawn on the same Machine. State
(`/var/lib/aki/docker` + `/var/lib/aki/hermes`) lives on a Fly volume
that survives Machine restarts. The api Machine is **privileged**;
that's an org-level approval from Fly. See
[`DEPLOY.md`](DEPLOY.md#privileged-mode) for what to do if your org
isn't approved yet.

## Zero → running, end to end

**The whole pipeline is now driven by [`DEPLOY.md`](DEPLOY.md) +
[`fly-deploy.sh`](fly-deploy.sh).** The sections below predate that
runbook and survive only as backing context for individual steps
(Neon setup, Cloudflare cert flow, etc.). Read `DEPLOY.md` first.

### 1. Accounts you need

- **Fly.io** — org created, billing card on file (production tier)
- **Neon** — production project, `pgvector` enabled on the default branch
- **Vercel** — production team, project imported from GitHub
- **Cloudflare** — domain registered (`aki.dev`) or transferred in; Pages
  not needed
- **Clerk** — production instance (separate from dev)
- **Pipedream** — Connect project (production)
- **Arcade** — production project
- **GitHub** — repo admin to set Actions secrets + GHCR package perms
- **Slack** — incoming webhook for `#deploys`

### 2. Neon production setup

1. Create a new project in `us-east-1` (matches Fly `iad`).
2. Enable the `vector` extension: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Copy both connection strings: the **pooled** (transaction mode) URL —
   that becomes `DATABASE_URL`, prefix scheme with `postgresql+asyncpg://`
   — and the **direct** URL — that becomes `DATABASE_URL_SYNC`.
4. The first `api-deploy` run will run `alembic upgrade head` against
   `DATABASE_URL_SYNC`. Migration `0003` was applied to live Neon by hand
   during dev; the CI step will be a no-op until 0004+ lands.

### 3. Cloudflare in front of `api.aki.dev`

1. Add `aki.dev` to Cloudflare (Full SSL strict).
2. In Fly, attach a certificate for `api.aki.dev` to `aki-api`:
   `flyctl certs add api.aki.dev --app aki-api`
3. Fly will print the CNAME target. Create the DNS record in Cloudflare
   **with proxy = DNS only** until the cert validates, then flip to
   proxied.
4. Set Cloudflare's SSL/TLS encryption mode to **Full (strict)**.
5. Cache rules: bypass `/health` and `/webhooks/*`; everything else can
   sit behind Cloudflare's default API cache (most routes set their own
   `Cache-Control: no-store` headers).

### 4. GHCR setup

The agent + api images are pushed to GHCR under `ghcr.io/<your-gh-org>/`.
On first push:

1. Open the package in GitHub → Package settings → **Manage Actions
   access** → add the repo with "Write".
2. Visibility → **Private** (control plane pulls from GHCR via the Fly
   builder).
3. The Fly builder pulls these images using
   `flyctl deploy --remote-only --image ghcr.io/...`; the API token for
   GHCR is the deploy-time `GITHUB_TOKEN` (no separate Fly registry creds
   needed because the workflow tags `latest` + pushes before calling
   `flyctl deploy`).

### 5. Populate secrets

Follow [`infra/secrets-bootstrap.md`](secrets-bootstrap.md). Do this
**before** the first deploy; the app will crashloop without
`DATABASE_URL` and `CLERK_SECRET_KEY`.

### 6. First deploy

See [`DEPLOY.md`](DEPLOY.md#5-deploy). One command:

```bash
FLY_ORG=<your-org> infra/fly-deploy.sh all
```

The script creates the apps, the api volume, Upstash Redis, deploys both
images, flips the api Machine to privileged, and smokes both healthchecks.
Re-running is idempotent.

### 7. Smoke test

```bash
curl https://api.aki.dev/health                            # → {"status":"ok"}
curl https://aki-browser-harness.fly.dev/healthz           # → {"status":"ok"}
curl https://app.aki.dev                                   # → Next.js landing (Vercel)
```

Sign in via Clerk, connect a toolkit, send a chat message. First message
per org pays one ~5-10s cold-start while dockerd spawns the per-org
Hermes container.

## CI/CD summary

- **Push to `main` touching `services/api/**`** → build image to GHCR,
  alembic `--check` (fail if pending), `upgrade head`, `flyctl deploy`,
  Slack on failure.
- **Push to `main` touching `services/agent/**`** → build + push image
  to GHCR. No deploy.
- **Push to `main` touching `apps/web/**`** → Vercel build (Vercel's
  own integration; not in this repo's workflows).
- **Push to `main` touching `services/browser-harness/**`** → harness
  lane's own workflow (not owned here).

## Observability

The dashboards in `infra/grafana/` are importable JSON for **Grafana
Cloud Free**. Datasource: a Prometheus-compatible scrape of Fly's
metrics endpoint. Per-service:

- `api.dashboard.json` — request rate, p50/p95/p99 latency, error rate,
  per-org cost burn
- `agent.dashboard.json` — Hermes container cold-start time, per-org
  active Machines, hibernation cycle counts
- `browser-harness.dashboard.json` — session count, avg session time,
  R2 upload bytes

PostHog (`POSTHOG_KEY` in `apps/web` env) covers product analytics for
the web app — out of scope for this infra lane.

## Things this lane explicitly does NOT cover

- SOC 2 paperwork / compliance frameworks (founder deferred)
- Stripe / billing wiring (deferred)
- Real SSO/SAML (Clerk org-scoped auth only, for now)
- Migration from Path B → Path A (Fly Machines API spawner) — see triggers
  in ADR-0001 §"What this defers"
- Anything inside `services/api/`, `apps/web/`, or
  `services/browser-harness/` source trees (owned by their respective lanes)
