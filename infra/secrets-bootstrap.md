# Secrets bootstrap

One-page runbook for populating every secret the control plane + GitHub
Actions need. Read alongside [`DEPLOY.md`](DEPLOY.md); the deploy script
verifies these are present and aborts if any are missing.

> **Never commit values.** This file lists names + sources only. Anything
> resembling a token, key, or webhook URL must be set via `fly secrets set`
> or in the GitHub repo settings, never in this repo.

## Set pattern

Fly app secrets (per app: `aki-api`, plus future apps):

```bash
fly secrets set --app aki-api \
  DATABASE_URL='...' \
  DATABASE_URL_SYNC='...' \
  CLERK_SECRET_KEY='...'
# (repeat per secret; or pass a single multi-line `--stdin` from a 1Password CLI session)
```

GitHub Actions secrets (repo → Settings → Secrets and variables → Actions):
set each as a **Repository secret** (or **Environment secret** if you have
a `production` environment configured).

## Inventory — Fly app `aki-api`

| Name                       | Source                                                                                                |
| -------------------------- | ----------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`             | Neon dashboard → project → Connection details → **Pooled (transaction)** connection string, `+asyncpg` scheme |
| `DATABASE_URL_SYNC`        | Neon dashboard → same project → **Direct** connection string (no pooler); psycopg2 scheme            |
| `CLERK_SECRET_KEY`         | Clerk dashboard → API Keys → Secret keys (`sk_live_…` in prod)                                       |
| `CLERK_WEBHOOK_SECRET`     | Clerk dashboard → Webhooks → endpoint for `https://api.aki.dev/webhooks/clerk` → Signing secret      |
| `CLERK_JWKS_URL`           | Clerk dashboard → API Keys → "Frontend API" → `${CLERK_JWT_ISSUER}/.well-known/jwks.json`            |
| `CLERK_JWT_ISSUER`         | Clerk dashboard → API Keys → "Frontend API" (the `https://<your-app>.clerk.accounts.dev` URL)        |
| `OPENAI_API_KEY`           | OpenAI dashboard → API keys → create a key scoped to the prod project                                |
| `PIPEDREAM_CLIENT_ID`      | Pipedream dashboard → Connect → OAuth Client → Client ID                                              |
| `PIPEDREAM_CLIENT_SECRET`  | Pipedream dashboard → Connect → OAuth Client → Client Secret                                          |
| `PIPEDREAM_PROJECT_ID`     | Pipedream dashboard → Project settings → Project ID                                                   |
| `ARCADE_API_KEY`           | Arcade dashboard → API Keys → generate prod key                                                       |
| `BROWSER_HARNESS_API_KEY`  | `openssl rand -hex 32` — same value goes into the browser-harness Fly app's secrets                  |
| `BROWSER_HARNESS_URL`      | `http://aki-browser-harness.internal:7901` (Fly 6PN) — public `https://aki-browser-harness.fly.dev` works too if you need to hit it from outside the org |
| `REDIS_URL`                | **Do not set by hand.** `infra/fly-deploy.sh redis` runs `fly redis create` + `fly redis attach`, which sets this secret on `aki-api` automatically. |
| `GHCR_PULL_USERNAME`       | GitHub username with read access to `ghcr.io/akiapp/aki-hermes` — used by the api Machine's entrypoint to pre-pull the Hermes image on boot. Optional; cold pull falls back to first chat. |
| `GHCR_PULL_TOKEN`          | Personal access token (classic) with `read:packages` scope. Optional, paired with `GHCR_PULL_USERNAME`. |

## Inventory — Fly app `aki-browser-harness`

| Name                              | Source                                                                                                |
| --------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `BROWSER_HARNESS_API_KEY`         | Same shared secret as on `aki-api`                                                                    |
| `BROWSER_HARNESS_R2_ENDPOINT`     | Cloudflare R2 → bucket → S3 API → `https://<account>.r2.cloudflarestorage.com`                        |
| `BROWSER_HARNESS_R2_ACCESS_KEY`   | Cloudflare R2 → API tokens → scoped to `aki-browser-profiles`                                         |
| `BROWSER_HARNESS_R2_SECRET_KEY`   | Same R2 token, secret half                                                                            |
| `STEEL_API_KEY`                   | Steel.dev dashboard → API keys                                                                        |
| `BROWSERBASE_API_KEY`             | Browserbase dashboard → API keys (optional fallback / per-platform routing)                           |
| `BROWSERBASE_PROJECT_ID`          | Browserbase dashboard → Project settings (required if `BROWSERBASE_API_KEY` is set)                   |
| `BROWSER_HARNESS_ALLOWED_HOSTS`   | Optional CSV SSRF allowlist for customers with internal tools                                         |
| `BROWSER_HARNESS_PLATFORM_ROUTES` | Optional JSON map `{ "linkedin.com": "browserbase" }` overriding the default backend per host         |

## Inventory — GitHub Actions repo secrets

| Name                       | Source                                                                                                |
| -------------------------- | ----------------------------------------------------------------------------------------------------- |
| `FLY_API_TOKEN`            | `fly tokens create deploy` scoped to `aki-api`; CI uses it to run `flyctl deploy`                     |
| `DATABASE_URL_SYNC`        | Same Neon direct URL as the app; CI uses it to run `alembic upgrade head` pre-deploy                  |
| `SLACK_DEPLOY_WEBHOOK`     | Slack workspace → Apps → Incoming Webhooks → channel `#deploys` → webhook URL                        |
| `GITHUB_TOKEN`             | Provided automatically; no action needed (used to push to GHCR)                                      |

## Inventory — Vercel (apps/web)

Set under Project Settings → Environment Variables (Production):

| Name                                  | Source                                                            |
| ------------------------------------- | ----------------------------------------------------------------- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`   | Clerk dashboard → API Keys → Publishable key (`pk_live_…`)         |
| `CLERK_SECRET_KEY`                    | Same as Fly                                                       |
| `NEXT_PUBLIC_API_BASE_URL`            | `https://api.aki.dev`                                              |
| `NEXT_PUBLIC_SITE_URL`                | `https://app.aki.dev`                                              |

## Rotation

- Clerk keys: rotate via Clerk dashboard; redeploy api + web.
- Neon: rotate the role password via the dashboard; update both
  `DATABASE_URL` and `DATABASE_URL_SYNC` everywhere they're set.
- `BROWSER_HARNESS_API_KEY`: regenerate with `openssl rand -hex 32`, set
  on **both** the harness Fly app and the api Fly app in the same
  `fly secrets set` invocation pair (run them back to back; the api will
  briefly fail harness calls otherwise).
- `FLY_API_TOKEN`: `fly tokens revoke <id>` then `fly tokens create deploy`;
  update the GHA repo secret. Not consumed by the running app — Path B
  doesn't spawn Machines, so the api Fly app doesn't need it as a secret.
- `REDIS_URL`: do not rotate by hand. `fly redis destroy aki-redis` +
  `infra/fly-deploy.sh redis` recreates and re-attaches.

## Verification

After bootstrap, confirm from a clean shell:

```bash
fly secrets list --app aki-api      # names only; values are hidden
gh secret list                       # repo secrets
```

Each Fly secret set triggers a rolling restart of the app, so plan
bootstrapping in one batched `fly secrets set` per app rather than one
secret at a time.
