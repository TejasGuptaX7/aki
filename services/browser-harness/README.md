# services/browser-harness

> ## ⚠️ v1 deprecated — replaced by `proxy/` (v2)
>
> The self-hosted Chromium pool documented below is **deprecated**.
> A replacement layer under [`proxy/`](./proxy/) routes per-`(org,
> agent, platform)` to **Steel.dev** (free tier, OSS-friendly) and
> **Browserbase** (production, auto-CAPTCHA). The wire contract for
> the replacement is in [`PROTOCOL_v2.md`](./PROTOCOL_v2.md) — it's a
> superset of v1's so the swap on the consumer side is "change
> `browser_harness_url`" and nothing else.
>
> **Deletion date for this v1 code**: 2026-08-15 (90 days from
> 2026-05-17 cut-over). Until then, both stacks run in parallel on
> different Fly apps. The control plane's `browser_harness_url`
> setting is the switch.
>
> | Concern | v1 (this file) | v2 ([proxy/](./proxy/)) |
> |---|---|---|
> | Browser source | local Chromium per agent | remote Steel / Browserbase |
> | Image size | ~1.2 GB (chromium bundled) | ~120 MB (pure Python) |
> | Cold start | 2–4 s (Chromium spawn) | 0.6–1.5 s (REST + WS) |
> | CAPTCHA | detect → `captcha_required` | same + Browserbase auto-solver |
> | Profile key | `(org, agent)` | `(org, agent, platform)` — separate Gmail/LinkedIn/Notion contexts |
> | Skills | `skills/_shared/*.py` exec'd in-process | stubbed in v2.0.0; reintroduced in v2.1 |
>
> **Migration path** for any consumer today (just `materialize.py`):
> change the URL setting from `browser_harness_url=http://aki-browser-harness.internal:7900`
> to `browser_harness_url=http://aki-browser-harness-v2.internal:7900`.
> No code change in the integrator; the v2 endpoint accepts the same
> `Authorization` / `X-Aki-Org-Id` / `X-Aki-Agent-Id` headers and
> exposes the same MCP tool names. Read [PROTOCOL_v2.md §8](./PROTOCOL_v2.md#8-registration-in-materializepy)
> for the one-line `Settings` change.
>
> See the [v2 Quickstart](#v2-quickstart-stelbrowserbase) section
> below before anything in the v1 docs.

---

## v1 (deprecated) — Self-hosted browser harness

The text below documents v1 as it shipped. Useful as a reference until
the v1 Fly app is torn down on 2026-08-15. Don't add new consumers
against it — point them at v2.

Self-hosted browser harness for Aki autonomous agents. Each agent gets its
own long-lived headless Chromium + persistent per-agent profile. The service
exposes browser primitives (navigate, click, type, extract, run skill) as
MCP tools over HTTP so Hermes can call them like any other connector.

> **Integration contract** for the control plane: see
> [PROTOCOL.md](./PROTOCOL.md). That file is the spec the
> `services/api/app/connectors/materialize.py` integration is written against.

## What's in here

```
services/browser-harness/
├── server.py            # v1 aiohttp MCP server (deprecated; runs the Chromium pool)
├── pool.py              # v1 per-(org, agent) Chromium + bh-daemon pool
├── storage.py           # v1 R2/S3 push-pull of cookies + localStorage + IDB
├── skills/              # per-agent skill PR target (v1 only; v2 stub in 2.0)
│   └── _shared/         # global fallback skills (e.g. google_search.py)
├── proxy/               # v2 replacement — Steel + Browserbase
│   ├── server.py        # v2 aiohttp MCP server (thin proxy)
│   ├── pool.py          # v2 per-(org, agent, platform) session pool
│   ├── router.py        # host pattern → (platform, backend) decision
│   ├── steel_adapter.py
│   ├── browserbase_adapter.py
│   ├── profile_store.py # R2-backed manifest store (vendor ids only)
│   ├── cdp.py           # async CDP WS client (~200 LOC)
│   ├── Dockerfile       # aki-browser-harness-v2:0.1.0
│   └── requirements.txt
├── PROTOCOL.md          # v1 wire contract (deprecated)
├── PROTOCOL_v2.md       # v2 wire contract — read this for new integrations
├── Dockerfile           # v1 image (deprecated)
├── docker-compose.yml   # v1 local dev stack (deprecated)
├── scripts/
│   ├── setup-r2.sh
│   ├── smoke-test-prod.sh   # v1 smoke
│   └── smoke-test-v2.sh     # v2 smoke (Steel + Browserbase)
├── requirements.txt
└── README.md            # you are here
```

## v2 Quickstart (Steel/Browserbase)

The v2 proxy needs three secrets at runtime:

| Env var | Where from |
|---|---|
| `BROWSER_HARNESS_API_KEY` | shared secret with the API gateway (same as v1) |
| `STEEL_API_KEY` | https://app.steel.dev → Settings → API Keys |
| `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` | https://browserbase.com/settings (Developer plan, $20/mo) |

Plus the same R2 vars as v1 if you want the per-(org, agent, platform)
manifests to persist across replicas (`BROWSER_HARNESS_R2_*`).

### Founder signup walkthrough

**Steel.dev — free tier (5 concurrent sessions, 15 min/session, $0.10/hr after free):**
1. Visit https://app.steel.dev — sign up with Google or email
2. Settings → API Keys → "Create new key", name it `aki-prod`
3. Copy the key (shown once); paste into `STEEL_API_KEY`
4. Free tier needs no card; upgrade to Hobby/Starter only when you
   exceed 500 requests/day or want sessions > 15 min

**Browserbase — Developer plan ($20/mo, 25 concurrent, 100 browser-hrs/mo, auto-CAPTCHA included):**
1. Visit https://browserbase.com/sign-up — sign up with Google
2. Skip the "Free" CTA and pick **Developer** ($20/mo). Free tier has
   no CAPTCHA solver, which defeats the reason we're using Browserbase
   for `linkedin`/`twitter`/CF-protected targets in the first place.
3. Add a card; Browserbase charges monthly + overage at $0.12/hr above 100 hrs
4. Settings → API Keys → "Create new key" → copy into `BROWSERBASE_API_KEY`
5. Settings → Projects → copy the project id into `BROWSERBASE_PROJECT_ID`
6. (Optional) Settings → Stealth → enable "Advanced Stealth Mode" globally —
   v2.0 sends `solveCaptchas:true` by default but advanced stealth is per-project

The agent will create accounts at Steel and Browserbase on the
founder's behalf only when the founder runs the signup steps above.
This service code never embeds vendor credentials at build time;
every key flows through Fly secrets / `.env` at runtime.

### Local smoke

```bash
cd services/browser-harness/proxy
pip install -r requirements.txt

export BROWSER_HARNESS_API_KEY=dev-secret
export STEEL_API_KEY=...
export BROWSERBASE_API_KEY=...
export BROWSERBASE_PROJECT_ID=...

python server.py           # listens on :7901
```

In another shell:

```bash
BROWSER_HARNESS_URL=http://localhost:7901 \
BROWSER_HARNESS_API_KEY=dev-secret \
STEEL_API_KEY=$STEEL_API_KEY \
BROWSERBASE_API_KEY=$BROWSERBASE_API_KEY \
BROWSERBASE_PROJECT_ID=$BROWSERBASE_PROJECT_ID \
  bash services/browser-harness/scripts/smoke-test-v2.sh
```

The smoke test (4 steps × 2 vendors):
1. **Steel run** — navigate `example.com` via the `default` platform
   (Steel by default routing); `extract_text` confirms "Example Domain";
   `list_platforms` confirms `backend=steel`
2. **Browserbase run** — navigate `example.com` with `X-Aki-Platform:
   linkedin` (linkedin → Browserbase per the default table); set a
   cookie via `js`; `release_platform persist=true`; re-navigate; verify
   the cookie **persisted across the release** (proves the Browserbase
   Context did its job)

Output ends with `both runs passed` on success. Cleans up vendor
sessions in a trap so a failed run doesn't leak billable time.

### Fly deploy (v2)

The v2 image is small enough that a dedicated app is the cleanest split:

```bash
flyctl apps create aki-browser-harness-v2
flyctl secrets set --app aki-browser-harness-v2 \
  BROWSER_HARNESS_API_KEY="$(openssl rand -hex 32)" \
  STEEL_API_KEY="..." \
  BROWSERBASE_API_KEY="..." \
  BROWSERBASE_PROJECT_ID="..." \
  BROWSER_HARNESS_R2_ENDPOINT="https://<acct>.r2.cloudflarestorage.com" \
  BROWSER_HARNESS_R2_BUCKET="aki-browser-profiles" \
  BROWSER_HARNESS_R2_ACCESS_KEY="..." \
  BROWSER_HARNESS_R2_SECRET_KEY="..." \
  BROWSER_HARNESS_R2_REGION="auto"

# Build + deploy from the proxy/ dir (no Chromium → fast build)
flyctl deploy --app aki-browser-harness-v2 \
  --dockerfile services/browser-harness/proxy/Dockerfile \
  --config services/browser-harness/proxy/fly.toml    # NOT included here; see PROTOCOL_v2 for the Fly recipe
```

> A dedicated `proxy/fly.toml` isn't shipped in this commit — v2 only
> needs one machine (no per-region Chromium to pin since the browsers
> live at the vendor), so the v1 fly.toml is too heavy. The integrator
> can either reuse v1's fly.toml stripped down to one shared-cpu-1x /
> 512 MB machine, or wait for the v2 deploy bundle that lands with the
> v1 retirement PR.

---

## How it works

```
                       MCP HTTP (JSON-RPC over POST /mcp)
                       Authorization: Bearer …
                       X-Aki-Org-Id / X-Aki-Agent-Id
                                │
                                ▼
                      ┌─────────────────────┐
                      │ server.py (aiohttp) │
                      │  validate auth      │
                      │  dispatch tool      │
                      └────────┬────────────┘
                               │
                               ▼  pool.acquire(org, agent)
                      ┌─────────────────────┐
                      │ pool.py             │
                      │ (org, agent) → Sess │
                      │  spawn Chromium     │ on miss
                      │  spawn bh-daemon    │
                      │  restore from R2    │
                      │  reap on idle/cap   │
                      └────────┬────────────┘
                               │
                               ▼ unix-socket IPC
                       browser-harness daemon
                               │
                               ▼ CDP WS
                       headless Chromium (per agent)
                               │
                               ▼ tar.gz on close
                       R2 / S3 / minio
                       <org>/<agent>/profile.tar.gz
```

Per-agent isolation is enforced two ways:

1. Each agent's Chromium has its own `--user-data-dir` and own CDP port.
2. Each agent's `browser-harness` daemon has its own `BU_NAME` (hash of org+agent)
   and its own `BH_RUNTIME_DIR`, so the IPC sockets never collide on the
   shared `/var/lib/aki/browser-profiles/<org>/<agent>/runtime/bu.sock`.

The aiohttp server is a single process. To scale horizontally, front it with
a sticky load balancer keyed on the `(X-Aki-Org-Id, X-Aki-Agent-Id)` tuple
(use the concatenation as the consistent-hash key). See
[PROTOCOL.md §5](./PROTOCOL.md#5-session-lifecycle-what-the-integrator-should-know).

## Local dev

```bash
cd services/browser-harness
docker compose up --build
# wait ~20s for the bucket setup + first chromium pull
```

This brings up:

- `browser-harness` on `:7900` (MCP endpoint at `/mcp`)
- `minio` on `:9000` (S3) + `:9001` (web console, login `aki` / `aki-dev-secret`)
- `minio-setup` (one-shot — creates the `aki-browser-profiles` bucket)

### Smoke test (the one in the task spec)

Navigate to Google, search "weather", extract the first organic result, and
verify the per-agent profile persists across two calls. Run from a host
terminal with `docker compose up` in another.

```bash
KEY=${BROWSER_HARNESS_API_KEY:-dev-secret-change-me}
ORG=00000000-0000-0000-0000-000000000001
AGENT=00000000-0000-0000-0000-0000000000aa

# 1) sanity: list tools
curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools | length'

# 2) run the google_search skill
curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":2,"method":"tools/call",
    "params":{"name":"run_skill","arguments":{"name":"google_search","args":{"query":"weather"}}}
  }' | jq '.result.content[0].text | fromjson'

# Expected:
# {
#   "ok": true,
#   "return_value": {
#     "title": "Weather - Google ...",
#     "url":   "https://...",
#     "snippet": "..."
#   },
#   "stdout": ""
# }

# 3) prove the profile persists — set a cookie on call A, read it on call B
#    (the Chromium between the two calls stays alive within the idle window;
#     to test the R2 roundtrip, call release_session between them).
curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"navigate","arguments":{"url":"https://example.com"}}}' > /dev/null

curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call",
       "params":{"name":"js","arguments":{"expression":"document.cookie=\"aki=hello;path=/\";document.cookie"}}}'

curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call",
       "params":{"name":"release_session","arguments":{}}}'

# Now hit example.com again — fresh Chromium, profile restored from R2
curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":6,"method":"tools/call",
       "params":{"name":"navigate","arguments":{"url":"https://example.com"}}}' > /dev/null

curl -sS http://localhost:7900/mcp \
  -H "Authorization: Bearer $KEY" \
  -H "X-Aki-Org-Id: $ORG" -H "X-Aki-Agent-Id: $AGENT" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":7,"method":"tools/call",
       "params":{"name":"js","arguments":{"expression":"document.cookie"}}}' \
  | jq '.result.content[0].text | fromjson'
# Should include "aki=hello"
```

## Configuration

All settings come from env vars (see `docker-compose.yml` for dev defaults).

### Required

| Var | Meaning |
|---|---|
| `BROWSER_HARNESS_API_KEY` | Shared secret. Every MCP request must carry it as `Authorization: Bearer <key>`. The control plane and the harness must agree. |

### R2 / S3 (optional but recommended for prod)

| Var | Default | Meaning |
|---|---|---|
| `BROWSER_HARNESS_R2_ENDPOINT` | _none — disables storage_ | S3-compatible endpoint URL (e.g. `https://<acct>.r2.cloudflarestorage.com`) |
| `BROWSER_HARNESS_R2_ACCESS_KEY` | _none_ | Access key id |
| `BROWSER_HARNESS_R2_SECRET_KEY` | _none_ | Secret access key |
| `BROWSER_HARNESS_R2_BUCKET` | `aki-browser-profiles` | Bucket name |
| `BROWSER_HARNESS_R2_REGION` | `auto` | Region (R2 doesn't care; AWS S3 does) |

When unset, profiles live only on the local volume — fine for dev, lossy
across restarts in prod.

### Pool tuning

| Var | Default | Meaning |
|---|---|---|
| `BROWSER_HARNESS_PROFILE_ROOT` | `/var/lib/aki/browser-profiles` | Local FS root for per-agent dirs |
| `BROWSER_HARNESS_SKILLS_ROOT` | `/var/lib/aki/browser-harness/skills` | Skill dir |
| `BROWSER_HARNESS_PORT_MIN` | `9300` | Lowest CDP port to allocate |
| `BROWSER_HARNESS_PORT_MAX` | `9999` | Highest CDP port |
| `BROWSER_HARNESS_IDLE_SECONDS` | `600` | Reap sessions idle for this long |
| `BROWSER_HARNESS_HARD_MAX_SECONDS` | `1800` | Hard wall-clock cap; orphan-defender |
| `BROWSER_HARNESS_CHROMIUM` | `/usr/bin/chromium` | Chromium binary |

### Security

| Var | Default | Meaning |
|---|---|---|
| `BROWSER_HARNESS_ALLOWED_HOSTS` | _empty_ | Comma-sep allowlist for internal hosts that should bypass the SSRF guard (RFC1918 / metadata IPs are blocked otherwise). Supports glob: `*.tools.acme.internal`. |

## Tools exposed

See [PROTOCOL.md §4](./PROTOCOL.md#4-tool-catalogue-v010) for the full
catalogue with arg/result shapes. Quick reference:

- `navigate`, `new_tab`, `close_tab`, `switch_tab`, `list_tabs`
- `click`, `type`, `fill`, `press_key`, `scroll`, `upload_file`
- `screenshot`, `extract_text`, `extract_html`, `page_info`
- `wait_for_load`, `wait_for_element`, `wait_for_network_idle`
- `js`, `cdp` (raw escape hatch), `http_get`
- `run_skill`, `list_skills` (per-agent Python skills under `skills/<org>/<agent>/`)
- `session_info`, `release_session`

## Skills

Skills are Python files under
`skills/<org_id>/<agent_id>/<name>.py` (or `skills/_shared/<name>.py` for
global fallbacks). The harness exec's them in a namespace where browser
primitives are pre-bound as sync wrappers:

```python
# skills/_shared/google_search.py
q = args.get("query")
navigate(f"https://www.google.com/search?q={q.replace(' ', '+')}")
wait_for_load()
result = js("document.querySelector('h3').innerText")
```

The skill assigns the return value to `result`; `stdout` is captured and
returned. See `skills/_shared/google_search.py` for the worked example used
in the smoke test.

In production, mount the skill root from a host volume so agent-written
skill PRs (the upstream model — agents propose `.py` files via the PR
workflow described in upstream `SKILL.md`) survive container restarts.

### Seed corpus

Every new agent starts with these `_shared` skills available so the
self-learning loop has something to bootstrap from. The signup skills all
follow the same defensive pattern (cookie banner dismissal, captcha
detection via `_signup_helpers.py`, structured result with `status` ∈
`{verification_email_sent, account_created, captcha_required, form_changed}`):

| Skill | Args | Notes |
|---|---|---|
| `google_search` | `query` | Used by the smoke test |
| `notion_signup` | `email`, `password`, `full_name?` | Magic-link or password depending on A/B |
| `linear_signup` | `email`, `workspace_name?` | Always magic-link; Turnstile is common |
| `hubspot_trial` | `email`, `password`, `full_name`, `company`, `industry?` | Multi-step form |
| `typeform_signup` | `email`, `password`, `full_name?` | Single page |
| `airtable_signup` | `email`, `password`, `full_name` | Onboarding survey skipped |
| `webflow_signup` | `email`, `password`, `full_name?` | Almost always returns `captcha_required` — expected |
| `mailchimp_signup` | `email`, `password`, `username` | Strict password rules; username must be globally unique |
| `clickup_signup` | `email`, `password`, `full_name?`, `workspace_name?` | Drops into onboarding wizard |

`_signup_helpers.py` (underscore-prefixed → not exposed via `list_skills`)
holds the cookie-banner patterns and the captcha-widget detector. Skills
load it via `load_helpers("_signup_helpers")` at their top.

All selectors carry a `# verified: 2026-05-16 (static review only)` marker
in the file header. Live-site verification was **not** done — we don't want
to create real accounts from a CI-style smoke. The skills are
production-shaped scaffolds: each is the right pattern but a selector may
have rotted between writing and the first real call. The agent's
self-edit-on-rot loop is what closes the gap.

## Operational notes

### Logs

`stdout` is line-delimited JSON. Every tool call emits one line:

```json
{"ts": 1734000000.5, "msg": "tool_call", "org_id": "...", "agent_id": "...",
 "tool": "navigate", "url": "https://example.com",
 "duration_ms": 823, "status": "ok", "request_id": "req_a1b2c3..."}
```

`status` is one of `ok`, `tool_error`, `timeout`, `internal_error`. For
tool errors, a `code` field carries the structured code from
[PROTOCOL.md §4](./PROTOCOL.md#4-tool-catalogue-v010).

### Captcha

When a navigated page contains text like "verify you are human" / "cloudflare
to access" / "captcha", the tool returns `isError: true` with
`code: captcha_required`. v0.1.0 does **not** attempt to auto-solve — the
agent decides whether to escalate to a human or invoke a per-customer
solver service. This is intentional: silently chewing on a captcha burns
both budget and trust.

### Horizontal scaling

The pool's state is in-memory. To run N replicas, the load balancer in front
of the service **must** be sticky-routed on `(X-Aki-Org-Id, X-Aki-Agent-Id)`
(use the concatenation as the consistent-hash key). A misroute is correct
but wasteful — see PROTOCOL.md §5.

### What's deliberately not here (v0.1.0)

- Captcha solvers (caller's choice, per-customer).
- Visual session livestream (the upstream `start_remote_daemon` exposes a
  `liveUrl` for Browser Use cloud browsers; for self-hosted, expose the CDP
  port via a separate authn'd route if you want noVNC).
- Quota / per-tenant rate limits (lives in the control plane gateway, not here).
- Agent skill PR machinery (the upstream model is a GitHub PR workflow; that
  pipeline pushes files into the mounted `skills/` dir — orchestration lives
  outside this service).

## Deployment (Fly Machines)

The production target is **Fly Machines**, one machine per region in
`{iad, sea, fra, syd}`. Per-region pinning matters: a French customer's
agent should render JS from a Frankfurt IP or every fraud system flags
them. Fly's per-second billing + the `auto_stop_machines = "stop"` setting
in `fly.toml` means idle regions cost ~$0.

### Prereqs

1. **Fly account.** `brew install flyctl` (or [`curl -L https://fly.io/install.sh | sh`](https://fly.io/docs/flyctl/install/)). `flyctl auth login`.
2. **Cloudflare R2 account.** A bucket + an R2 API token scoped to it; see `scripts/setup-r2.sh`.
3. **GitHub Container Registry.** The deploy workflow pushes to GHCR; no extra setup beyond enabling GHCR for the org. The workflow uses the built-in `GITHUB_TOKEN` to push.
4. **GH secrets** in the repo settings:
   - `FLY_API_TOKEN` — `flyctl auth token`
   - `SLACK_DEPLOY_WEBHOOK` — Slack Incoming Webhook URL for failure pings
   - `BROWSER_HARNESS_API_KEY_PROD` — the same shared secret you set in Fly; used by the post-deploy smoke step

### Zero-to-deployed walkthrough

```bash
# 1) Create the Fly app (one-time, manual — keep app-creation out of CI)
flyctl apps create aki-browser-harness

# 2) Create per-region volumes for the local profile cache (R2 is SoT)
for region in iad sea fra syd; do
  flyctl volumes create browser_profiles \
      --app aki-browser-harness \
      --region "$region" --size 20 -y
done

# 3) Set up R2 (bucket + bring back creds from the dashboard)
CF_ACCOUNT_ID=... CF_API_TOKEN=... R2_BUCKET=aki-browser-profiles \
    bash services/browser-harness/scripts/setup-r2.sh

# 4) Set Fly secrets (no values in fly.toml; everything sensitive lives here)
flyctl secrets set --app aki-browser-harness \
  BROWSER_HARNESS_API_KEY="$(openssl rand -hex 32)" \
  BROWSER_HARNESS_R2_ENDPOINT='https://<cf-acct>.r2.cloudflarestorage.com' \
  BROWSER_HARNESS_R2_BUCKET='aki-browser-profiles' \
  BROWSER_HARNESS_R2_ACCESS_KEY='<from dashboard>' \
  BROWSER_HARNESS_R2_SECRET_KEY='<from dashboard>' \
  BROWSER_HARNESS_R2_REGION='auto'

# 5) Activate the GitHub Actions workflow (see "GHA discovery" below)

# 6) Push to main on a change to services/browser-harness/** — the workflow
#    builds, pushes to GHCR, runs `flyctl deploy --image <sha>`, and the
#    post-deploy step runs scripts/smoke-test-prod.sh against the public URL.

# Manual deploy from a laptop (skip the workflow):
flyctl deploy --app aki-browser-harness \
  --config services/browser-harness/fly.toml \
  --dockerfile services/browser-harness/Dockerfile

# Verify
BROWSER_HARNESS_URL=https://aki-browser-harness.fly.dev \
BROWSER_HARNESS_API_KEY=<the secret you set above> \
  bash services/browser-harness/scripts/smoke-test-prod.sh
```

### GHA discovery — required one-time step

GitHub Actions only picks up workflows under `.github/workflows/` at the
**repo root**. The deploy workflow is shipped at
`services/browser-harness/.github/workflows/browser-harness-deploy.yml`
to keep it co-located with the service. To activate it, the integrator
symlinks it from the repo root (one-time):

```bash
ln -s ../../services/browser-harness/.github/workflows/browser-harness-deploy.yml \
      .github/workflows/browser-harness-deploy.yml
git add .github/workflows/browser-harness-deploy.yml
git commit -m "activate browser-harness deploy workflow"
```

(A copy instead of a symlink works too — the symlink is cleaner because
edits to the source file flow through without re-committing the workflow.)

### Operational details

- **Fly app name**: `aki-browser-harness`. Public URL: `https://aki-browser-harness.fly.dev`. Internal (within the Fly org): `http://aki-browser-harness.internal:7900`. Point the control plane's `BROWSER_HARNESS_URL` at the internal hostname when both services are in the same Fly org — saves the TLS round-trip and avoids cold-starting machines from public HTTP probes.
- **Sticky routing**: Fly's L4 proxy doesn't natively hash on custom headers. Two paths:
  1. Front the harness with the control plane's gateway and hash `(org, agent)` there before forwarding to a specific machine via `Fly-Force-Instance-Id`.
  2. Run one machine per region (`min_machines_running = 0`, `auto_start = true`) and rely on the per-machine pool serving all that region's traffic. Default config does (2).
- **Rolling secrets**: `flyctl secrets set` triggers a rolling restart. Sessions in flight drain via `kill_timeout = "30s"` (matches the harness's session shutdown path that persists profiles to R2 — see `pool.stop()`).
- **Volume backups**: R2 is the source of truth, so a volume loss = next request pulls from R2. Fly takes nightly volume snapshots; restore is via `flyctl volumes restore`.
