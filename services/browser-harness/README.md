# services/browser-harness

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
├── server.py            # aiohttp MCP server (JSON-RPC 2.0 over HTTP)
├── pool.py              # per-(org, agent) Chromium + bh-daemon pool
├── storage.py           # R2/S3 push-pull of cookies + localStorage + IDB
├── skills/              # per-agent skill PR target (mount as volume in prod)
│   └── _shared/         # global fallback skills (e.g. google_search.py)
├── PROTOCOL.md          # integration contract — read this for materialize.py
├── Dockerfile           # aki-browser-harness:0.1.0
├── docker-compose.yml   # local dev: harness + minio (R2 emulator)
├── requirements.txt
└── README.md            # you are here
```

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
