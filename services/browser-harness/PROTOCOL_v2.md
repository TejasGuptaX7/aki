# Browser Harness v2 — MCP Protocol Contract

> **Status**: replacement for [`PROTOCOL.md`](./PROTOCOL.md) (v1). v1
> remains the source of truth for the deployed self-hosted harness
> until the 90-day deprecation expires; see the v1 deprecation banner
> in [`README.md`](./README.md). This file is the contract for the
> proxy layer under [`proxy/`](./proxy/) that fronts Steel.dev (free
> tier) and Browserbase (production) instead of running our own
> Chromium pool.

> Version: `2.0.0`. The wire surface is intentionally a **superset** of
> v1 — every header and tool name the
> `services/api/app/connectors/materialize.py` integration emits today
> continues to work — so the migration is "swap `browser_harness_url`
> in settings, redeploy the API, done." Anything new in v2 lives behind
> optional headers or new tools that v1 callers can ignore.

---

## 1. What changed vs v1

| Concern | v1 | v2 |
|---|---|---|
| Browser source | local Chromium pool managed by `pool.py` | remote sessions on Steel.dev or Browserbase |
| Profile key | `(org_id, agent_id)` | `(org_id, agent_id, platform)` — separate profiles per logical platform |
| Profile storage | tar.gz to R2 | native: Steel `profileId` or Browserbase `contextId`, referenced by R2-stored mapping |
| Captcha | text/widget detect → `captcha_required` | same, plus Browserbase auto-solver when enabled by tier |
| Routing decision | none (one Chromium per agent) | host pattern → vendor (defaults in §3); explicit override via `X-Aki-Platform` |
| `tools/list` | 24 tools | superset: 24 v1 tools + `switch_platform`, `list_platforms`, `release_platform` |

Everything else (auth header, error code names, JSON-RPC envelope) is
**identical** to v1. A v1 client that never sends `X-Aki-Platform`
and never calls a v2-only tool will work against the v2 endpoint
unchanged — it just gets the auto-routed platform behavior.

---

## 2. Endpoint shape

| | |
|---|---|
| Transport | MCP Streamable HTTP (JSON-RPC 2.0 over HTTP POST), same as v1 |
| URL (dev) | `http://localhost:7901/mcp` (note port 7901 — v1 stays on 7900 during the transition) |
| URL (Fly) | `http://aki-browser-harness-v2.internal:7900/mcp` (separate Fly app) |
| Health | `GET /healthz` → `{"status":"ok"}` (no auth) |
| Readiness | `GET /readyz` → `200` once the router + profile store are loaded |
| Diagnostics | `GET /debug/platforms` → routing table dump (auth-gated; for the founder, not the agent) |

---

## 3. Routing (the platform decision)

The proxy routes every request to **one** of two vendors based on a
**platform** string. The platform is determined in this order:

1. **`X-Aki-Platform: <name>` header** if present. Caller wins; this
   bypasses host inference. Useful when the agent wants to keep a
   sequence of calls on one session even though the URLs span hosts.
2. **Most-recently-bound platform for this `(org, agent)`** if a
   prior `navigate` in the same minute established one.
3. **Host-pattern lookup** on the `navigate.url` argument (only meaningful
   for navigate/new_tab; tools that take no URL fall back to rule 2 and
   error with `no_active_platform` if no session exists yet).

### Default routing table (v2.0.0)

| Platform | Host patterns | Backend | Why |
|---|---|---|---|
| `linkedin` | `linkedin.com`, `*.linkedin.com` | Browserbase | aggressive bot mitigation; need solved CAPTCHAs and stealth fingerprint |
| `twitter` | `twitter.com`, `x.com`, `*.x.com` | Browserbase | same |
| `cloudflare_protected` | matched at runtime when navigate returns a Cloudflare challenge body | Browserbase | dynamic fallback; the proxy retries the request through Browserbase if Steel hits a CF wall |
| `default` | everything else | Steel | cheap and unlimited within the free tier; fine for SaaS signup flows that don't gate on bot detection |

Customers can extend the table via env (`BROWSER_HARNESS_PLATFORM_ROUTES`,
JSON map of `host_pattern → {platform, backend}`); see
[`proxy/router.py`](./proxy/router.py).

### Profile key shape

R2 key: `<org_id>/<agent_id>/<platform>/manifest.json`

Manifest contents (one of):

```jsonc
{ "backend": "steel",       "steel_profile_id": "prf_…" }
{ "backend": "browserbase", "browserbase_context_id": "ctx_…" }
```

When a session is requested for a `(org, agent, platform)` that has no
manifest, the proxy:
1. Calls the backend's create-context API (Browserbase) or create-profile
   API (Steel).
2. Writes the manifest to R2.
3. Creates the actual session attached to the new context/profile.

When the manifest exists, the proxy creates a new session attached to the
existing context/profile — cookies/localStorage/IndexedDB persist via the
vendor, not via our own tar.gz round-trip.

---

## 4. Required headers (same as v1, plus one optional)

```
Authorization: Bearer <BROWSER_HARNESS_API_KEY>
X-Aki-Org-Id: <org_uuid>
X-Aki-Agent-Id: <agent_uuid>
X-Aki-Platform: <name>          # OPTIONAL; overrides host-based routing
X-Aki-Request-Id: <opaque>       # OPTIONAL; echoed in _meta
Content-Type: application/json
```

Validation errors map to the same HTTP 401 shape v1 emits.

The `BROWSER_HARNESS_API_KEY` is a separate secret from any vendor key
(Steel/Browserbase API keys never leave the proxy process — they're in
Fly secrets, not the wire).

---

## 5. Tool catalogue (v2)

### v1 tools — wire-compatible

Same names, same arg shapes, same result shapes as
[`PROTOCOL.md §4`](./PROTOCOL.md#4-tool-catalogue-v010). v2.0.0 ships
working implementations of:

`navigate`, `new_tab`, `close_tab`, `switch_tab`, `list_tabs`,
`click`, `type`, `fill`, `press_key`, `scroll`,
`screenshot`, `extract_text`, `extract_html`, `page_info`,
`wait_for_load`, `wait_for_element`, `js`, `cdp`,
`session_info`, `release_session`.

### v1 tools — `not_implemented_in_v2` in v2.0.0 (returns `isError:true`)

These are stub-listed in `tools/list` to preserve wire compat, but
calling them returns `{code: "not_implemented_in_v2", detail: "…"}`:

`wait_for_network_idle`, `upload_file`, `http_get`,
`run_skill`, `list_skills`.

The agent never *needs* these for the autonomous-signup flows that
motivated v1 — they were nice-to-have. They'll be implemented or
formally removed in v2.1.

### v2-only tools (new in v2.0.0)

| Name | Args | Result |
|---|---|---|
| `switch_platform` | `{platform: string}` | `{ok: true, platform, backend, session_id}` — explicit binding; subsequent toolless-URL calls route here |
| `list_platforms` | `{}` | `{platforms: [{platform, backend, session_id, started_at_ago_seconds, idle_at_ago_seconds}]}` — what's live for this `(org, agent)` |
| `release_platform` | `{platform: string, persist?: bool = true}` | `{ok: true}` — releases one platform's session (Browserbase context auto-persists; Steel profile auto-persists) |

`persist:false` on `release_platform` deletes the underlying
Steel profile or Browserbase context too, **wiping the platform's
cookies**. Default is `persist:true` — keep the context, just drop the
in-flight session.

---

## 6. Error codes (additions vs v1)

All v1 codes still apply (`ssrf_blocked`, `captcha_required`,
`navigation_failed`, `element_not_found`, `timeout`, `js_error`,
`bad_args`, `internal_error`). v2 adds:

| Code | Meaning |
|---|---|
| `no_active_platform` | tool called that requires a session but no `navigate`/`switch_platform` has bound one for this `(org, agent)` yet |
| `vendor_quota_exhausted` | the chosen backend rejected the create-session call (Steel free tier hit, Browserbase concurrent cap, etc.). `detail` includes the vendor's message |
| `vendor_unavailable` | the chosen backend's API is down (5xx from Steel or Browserbase). The proxy retries once before raising |
| `not_implemented_in_v2` | tool exists in the catalogue for wire-compat but has no working implementation in v2.0.0 |
| `manifest_corrupt` | the R2 manifest for `(org, agent, platform)` couldn't be parsed; the proxy creates a fresh context and overwrites |

---

## 7. Session lifecycle vs v1

- **Cold start**: per-`(org, agent, platform)`, one REST round-trip to the
  chosen backend (~600–1500 ms). On vendor side, the browser is allocated
  from their warm pool. v1's local-Chromium spawn was ~2–4 s.
- **Idle reaping**: not our job — both vendors stop billing once the WS
  closes. The proxy holds the WS open for `idle_seconds` (default 600)
  per session, then closes it. Next call rents a new session against
  the same context/profile.
- **Hard cap**: Steel free tier caps sessions at 15 min wall-clock;
  Browserbase caps at `timeout` we pass (default 3600 s on the
  Developer plan). The proxy enforces neither — vendor terminates,
  proxy detects WS close, returns `vendor_unavailable` on the next
  call which transparently triggers a fresh session.
- **Horizontal scaling**: the proxy is stateless **between** requests —
  the per-`(org, agent, platform)` session handle lives in memory while
  the WS is open. The R2 manifest is the durable record. A sticky LB is
  no longer required; misroutes cost one extra REST round-trip (vendor
  reconnects to the same context/profile) but don't corrupt state.

---

## 8. Registration in `materialize.py`

**Zero code changes required** for the swap.
[`services/api/app/connectors/materialize.py`](../api/app/connectors/materialize.py)
already emits the right MCP entry; the only change the integrator
makes is the `browser_harness_url` setting:

```python
# Before (v1, today):
browser_harness_url = "http://aki-browser-harness.internal:7900"

# After (v2):
browser_harness_url = "http://aki-browser-harness-v2.internal:7900"
```

The control plane can stage this per-org or globally via a
`Settings` field rename, depending on how cautious the rollout is.

---

## 9. Stability / change policy

Same as v1 (§7 of PROTOCOL.md): tool name/arg/result shapes are SemVer
stable within the major. New tools and new optional args are minor
bumps. Removing tools or changing the auth header set is a major bump.

The transition v1 → v2 is a **major** bump (different default routing,
different profile key shape) but is sequenced via the dual-deploy
(both URLs live, integrator flips the setting) rather than a flag-day
break.
