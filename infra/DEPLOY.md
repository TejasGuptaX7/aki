# Aki — Fly.io deploy runbook

End-to-end "zero to running" for the Aki control plane (`services/api`) and
browser-harness v2 proxy (`services/browser-harness/proxy`) on Fly Machines,
backed by Neon (Postgres) and Upstash on Fly (Redis).

Per-org Hermes containers run via Path B (ADR-0001) with a sidecar dockerd
inside the api Machine (ADR-0002). No Fly Machines API spawn path.

If you need the "why this shape" rationale, read
[`decisions/0001-deploy-target.md`](decisions/0001-deploy-target.md) and
[`decisions/0002-fly-with-dind.md`](decisions/0002-fly-with-dind.md) first.
Otherwise, skip to **§1 Prerequisites** and work top to bottom.

## Topology

```
                ┌──────────────────────────── Fly org (iad) ───────────────────────────┐
                │                                                                       │
   Cloudflare ──┼──→  aki-api Machine (privileged)                                      │
   api.aki.dev  │      │                                                                │
                │      ├─ uvicorn :8000 ──── /var/run/docker.sock ──┐                   │
                │      ├─ dockerd (sidecar process)                 │                   │
                │      │     storage: /var/lib/aki/docker  ─── volume aki_api_data      │
                │      └─ per-org Hermes containers  ─── /var/lib/aki/hermes (volume)   │
                │                                                                       │
   Cloudflare ──┼──→  aki-browser-harness Machine(s)                                    │
   bh.aki.dev   │      └─ python proxy :7901  ─── R2 (profile store)                    │
   (optional)   │                                                                       │
                │       Upstash for Redis on Fly (REDIS_URL secret on aki-api)          │
                └───────────────────────────────────────────────────────────────────────┘

                Neon (us-east-1)  ────── DATABASE_URL / DATABASE_URL_SYNC
                Cloudflare R2     ────── BROWSER_HARNESS_R2_*
                Vercel            ────── apps/web (Vercel-owned config, not in this lane)
                GHCR              ────── ghcr.io/akiapp/api, ghcr.io/akiapp/aki-hermes
```

## 1. Prerequisites

| What                                     | How                                                          |
| ---------------------------------------- | ------------------------------------------------------------ |
| `flyctl` ≥ 0.3                           | `brew install flyctl` or `curl -L https://fly.io/install.sh \| sh` |
| `jq`                                     | `brew install jq`                                            |
| Fly account, org with billing on file    | sign up, add card                                            |
| Fly org enabled for privileged Machines  | email `support@fly.io`; see [Privileged mode](#privileged-mode) for the fallback if denied |
| Neon project (`us-east-1`)               | `vector` extension enabled on default branch                 |
| Cloudflare account + domain `aki.dev`    | Full (strict) SSL                                            |
| Cloudflare R2 bucket `aki-browser-profiles` | + API token scoped to the bucket                          |
| Steel.dev account                        | API key                                                      |
| Browserbase account (optional fallback)  | API key + project id                                         |
| Clerk production instance                | JWKS URL, JWT issuer, secret key                             |
| OpenAI / Anthropic prod API key          |                                                              |
| GHCR repo perms                          | `aki-hermes` image must be readable from CI; for the api `entrypoint.sh` pre-pull, set `GHCR_PULL_USERNAME`/`GHCR_PULL_TOKEN` secrets (read scope) |

## 2. One-time Fly setup

```bash
flyctl auth login
export FLY_ORG=<your-fly-org-slug>

# Sanity check: confirm the org can use privileged Machines. If you get a
# 403 on the privileged stage of fly-deploy.sh later, see §"Privileged mode"
# for the fallback. There is no API to query the flag preemptively.
```

## 3. Populate secrets

Follow [`secrets-bootstrap.md`](secrets-bootstrap.md). The deploy script
fails fast if anything required is missing — `fly secrets list` will look
empty until you actually do this step.

Order matters once: `REDIS_URL` is set automatically by `fly redis attach`,
so leave it alone in `secrets-bootstrap.md` and let the deploy script's
`redis` stage create + attach.

## 4. Neon

1. Create the project in `us-east-1` (matches Fly `iad`).
2. `CREATE EXTENSION IF NOT EXISTS vector;`
3. Grab two URLs from the Neon dashboard:
   - **Pooled (transaction)** — set as `DATABASE_URL`. Replace the scheme
     prefix with `postgresql+asyncpg://` (everything after the scheme is
     unchanged).
   - **Direct** — set as `DATABASE_URL_SYNC`. Keep the default
     `postgresql://` scheme; alembic uses psycopg2.
4. Run migrations once by hand against the direct URL:
   ```bash
   cd services/api
   DATABASE_URL_SYNC='<direct neon url>' alembic upgrade head
   ```
   CI takes over from migration 0004+.

## 5. Deploy

```bash
# Inspect each stage first; the script tells you what it'll do.
infra/fly-deploy.sh apps
infra/fly-deploy.sh volumes
infra/fly-deploy.sh redis            # creates + attaches Upstash; sets REDIS_URL
infra/fly-deploy.sh deploy           # builds + ships api + proxy
infra/fly-deploy.sh privileged       # flips api Machine to privileged
infra/fly-deploy.sh check            # GET /health, /healthz
```

Or the full pipeline in one go:

```bash
FLY_ORG=<your-org> infra/fly-deploy.sh all
```

The script is idempotent — re-running skips anything already in the right
state, so it doubles as the day-2 redeploy command after a code change.

### What "deploy" actually builds

| App                    | Dockerfile                                      | Build context                          |
| ---------------------- | ----------------------------------------------- | -------------------------------------- |
| `aki-api`              | `infra/fly/api/Dockerfile`                      | repo root                              |
| `aki-browser-harness`  | `services/browser-harness/proxy/Dockerfile`     | `services/browser-harness/proxy/`      |

The api Dockerfile wraps `services/api`'s python image with dockerd, the
docker CLI, iptables, and a small `entrypoint.sh` that:

1. starts `dockerd --host=unix:///var/run/docker.sock` in the background
2. waits up to 60s for the socket to be ready
3. optionally pre-pulls `ghcr.io/akiapp/aki-hermes:<tag>` (skipped if
   `GHCR_PULL_TOKEN` isn't set — cold pull falls back to the first chat)
4. exec's uvicorn

If uvicorn or dockerd exits, the script kills the other and the Machine
restarts clean.

## 6. Privileged mode

The api Machine runs dockerd inside its own VM. dockerd needs
`CAP_SYS_ADMIN` (mount, cgroup), `CAP_NET_ADMIN` (iptables for the bridge
network), and a few others. Fly Machines run unprivileged by default; the
deploy script's `privileged` stage patches each api Machine's config via
the Fly Machines REST API:

```
POST /v1/apps/aki-api/machines/<id>   { "config": { ..., "guest": { ..., "privileged": true } } }
```

Two failure modes:

- **403 from the Machines API.** Your Fly org isn't enabled for
  privileged Machines. Email `support@fly.io` requesting "privileged
  Machines on org `<slug>` for nested dockerd in our control plane" —
  approval is per-org and typically same-day. Until then, set
  `SKIP_PRIVILEGED=1` to skip the flip; dockerd will fail to start and
  the api Machine will crash-loop, but the proxy app + Neon + Redis
  will be live so you can verify the rest of the stack.

- **Org permanently denied.** Fall back to a single Hetzner CX32 or
  Hetzner Cloud node with docker + docker-compose. The
  `services/api/Dockerfile` runs directly there with no wrapper.
  Out of scope for this runbook; left as a tracked TODO in ADR-0002.

## 7. Domains

```bash
flyctl certs add api.aki.dev --app aki-api
# Fly prints a CNAME target — create the record in Cloudflare DNS-only
# first so the ACME validation works, then flip to proxied.
flyctl certs check api.aki.dev --app aki-api   # wait for status: issued
```

Cloudflare config:

- SSL/TLS encryption → **Full (strict)**
- Cache rules: bypass `/health`, `/webhooks/*`; default everywhere else
  (api routes set `Cache-Control: no-store` on their own)

The proxy app is reached internally by the api at
`http://aki-browser-harness.internal:7901` over Fly's 6PN — no public
hostname needed unless you want one for direct CDP debugging.

## 8. Smoke test

```bash
curl -fsSL https://api.aki.dev/health        # → {"status":"ok"}
curl -fsSL https://aki-browser-harness.fly.dev/healthz
```

Then sign in via Clerk on the web app, connect one toolkit, send a chat.
The first message per org pays one cold-start (~5-10s) while dockerd
spawns the per-org Hermes container; subsequent messages are
sub-second.

## 9. Day-2 ops

| Task                                     | Command                                                       |
| ---------------------------------------- | ------------------------------------------------------------- |
| Redeploy api after code change           | `infra/fly-deploy.sh deploy`                                  |
| Tail api logs (uvicorn + dockerd)        | `flyctl logs --app aki-api`                                   |
| SSH into the api Machine                 | `flyctl ssh console --app aki-api`                            |
| Inspect live per-org Hermes containers   | `flyctl ssh console --app aki-api -C 'docker ps'`             |
| Restart api (forces dockerd reload)      | `flyctl machine restart --app aki-api`                        |
| Grow the api volume                      | `flyctl volume extend <id> --size <gb> --app aki-api`         |
| Rotate `BROWSER_HARNESS_API_KEY`         | set on both apps in back-to-back `fly secrets set` calls      |
| Read Redis URL (without printing value)  | `flyctl redis status aki-redis`                               |

## 10. What this lane explicitly does NOT cover

- SOC 2 paperwork (founder deferred).
- Stripe / billing wiring (deferred).
- Real SSO/SAML (Clerk org-scoped auth only).
- `apps/web` deploy (owned by the web lane; Vercel + their GH integration).
- Migration from Path B → Path A (Fly Machines API spawner). When the
  triggers in ADR-0001 §"What this defers" hit, that's a separate lane.
