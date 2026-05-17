# Aki infra

Everything needed to take Aki from zero to a running production deploy on
Fly + Vercel + Neon + Cloudflare. This is the founder runbook.

```
infra/
├── README.md              ← you are here
├── secrets-bootstrap.md   ← every secret name + where its value comes from
├── fly/
│   ├── api.toml           ← Fly Machines config for services/api
│   └── agent.md           ← why services/agent has no fly.toml (per-org spawn)
└── grafana/
    ├── api.dashboard.json
    ├── agent.dashboard.json
    └── browser-harness.dashboard.json
```

The three services:

| Service                    | Where it runs                         | Owned config                                  |
| -------------------------- | ------------------------------------- | --------------------------------------------- |
| `services/api`             | Fly app `aki-api` (always-on)         | `infra/fly/api.toml`                          |
| `services/agent` (Hermes)  | Per-org Fly Machine, spawned on demand | GHCR image only, no Fly app — see `fly/agent.md` |
| `services/browser-harness` | Fly app `aki-browser-harness`         | `services/browser-harness/fly.toml` (owned by harness lane) |
| `apps/web`                 | Vercel                                | `apps/web/vercel.json`                        |

## Open architectural question — DO NOT skip this

`services/api/app/agent_runtime.py` spawns per-org Hermes containers via
`docker.from_env()`, which talks to `/var/run/docker.sock`. **Fly Machines
does not expose a Docker daemon to apps.** The api Dockerfile builds
correctly and starts on Fly, but the spawn path will raise on the first
chat message.

Two paths forward (pick **one**, then file a backend ticket):

**(a)** Host `services/api` on **Railway** or a small **EC2** instance
where `docker.sock` is available. Keep agent_runtime.py as-is. Pros:
zero code change. Cons: another platform, no Fly's built-in proxy/TLS,
have to wire CI separately.

**(b)** Swap `docker.from_env()` for a thin **Fly Machines API** client
inside agent_runtime.py. Pros: everything stays on Fly, per-org Machines
get all of Fly's volume + region story for free. Cons: a real backend
change (~few hundred lines incl. tests), needs `FLY_API_TOKEN` with
`machines:write` + `volumes:write` on the api app.

**Recommended: (b).** Cheaper long-term, gives us per-org regions and
volumes for free, and keeps observability in one place.

Tracked TODO in `services/api/Dockerfile` and `infra/fly/api.toml`.

## Zero → running, end to end

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

```bash
# api
flyctl apps create aki-api --org <your-fly-org>
flyctl ips allocate-v4 --app aki-api    # (or -v6; one shared v4 is fine to start)
flyctl deploy --config infra/fly/api.toml --remote-only

# agent image (no Fly app; just push the image once so the api has
# something to spawn from)
gh workflow run agent-image-build.yml --ref main

# browser-harness (owned by the harness lane)
cd services/browser-harness && flyctl deploy
```

After that, `git push origin main` triggers the workflows:

- `.github/workflows/api-deploy.yml` → build, migrate, deploy
- `.github/workflows/agent-image-build.yml` → build + push agent image
- (harness lane ships its own workflow)

### 7. Smoke test

```bash
curl https://api.aki.dev/health        # → {"status":"ok"}
curl https://app.aki.dev               # → Next.js landing
```

Sign in via Clerk, connect a toolkit (Gmail / Slack), send a chat
message. The first message will fail until the docker.sock-on-Fly
question is resolved (see top of this file).

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
- The `docker.from_env()` → Fly Machines API migration (backend lane)
- Anything inside `services/api/`, `apps/web/`, or
  `services/browser-harness/` source trees (owned by their respective lanes)
