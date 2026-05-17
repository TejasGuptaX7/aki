# Browser Harness — MCP Protocol Contract

This file is the **wire contract** for integrating `services/browser-harness`
into the control plane (`services/api/app/connectors/materialize.py`). Anything
about deployment, internals, or per-tool semantics that **isn't** wire-visible
lives in `README.md` instead.

> Version: `0.1.0`. Breaking changes bump the major and gate behind a
> `?version=` query param for at least one minor release.

---

## 1. Endpoint shape

| | |
|---|---|
| Transport | MCP **Streamable HTTP** (single endpoint, JSON-RPC 2.0 over HTTP POST) |
| URL (dev) | `http://localhost:7900/mcp` |
| URL (in-cluster) | `http://browser-harness.aki.internal:7900/mcp` |
| Health check | `GET /healthz` → `{"status":"ok"}` (no auth) |
| Readiness | `GET /readyz` → `200` once the pool has finished startup |

The endpoint accepts a single JSON-RPC request per POST. The server may reply
with a JSON body (`Content-Type: application/json`) or an SSE stream
(`Content-Type: text/event-stream`) if the client sent
`Accept: text/event-stream` — for v0.1.0 the server always replies with JSON.

---

## 2. Required headers on every request

```
Authorization: Bearer <BROWSER_HARNESS_API_KEY>
X-Aki-Org-Id: <org_uuid>
X-Aki-Agent-Id: <agent_uuid>
Content-Type: application/json
```

| Header | Required | Meaning |
|---|---|---|
| `Authorization` | yes | Shared secret. Server compares to env `BROWSER_HARNESS_API_KEY`. Constant-time compare. |
| `X-Aki-Org-Id` | yes | Org UUID. Profile/skill scope. Must match `^[0-9a-fA-F-]{36}$`. |
| `X-Aki-Agent-Id` | yes | Agent UUID. Browser session is keyed on `(org_id, agent_id)`. Same validation as above. |
| `X-Aki-Request-Id` | optional | Echoed back in `_meta.request_id` for tracing; generated if absent. |

Any missing/invalid header → HTTP `401 Unauthorized` with JSON body
`{"error": "unauthorized", "detail": "..."}` (NOT a JSON-RPC error envelope —
auth fails before JSON-RPC parsing).

---

## 3. JSON-RPC envelope

Standard MCP 2025-03-26 Streamable HTTP. The methods we implement:

### `initialize`

Required by spec. Returns server capabilities.

```jsonc
// request
{"jsonrpc":"2.0","id":1,"method":"initialize",
 "params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"hermes","version":"0.13.0"}}}

// response
{"jsonrpc":"2.0","id":1,"result":{
   "protocolVersion":"2025-03-26",
   "capabilities":{"tools":{"listChanged":false}},
   "serverInfo":{"name":"aki-browser-harness","version":"0.1.0"}}}
```

### `notifications/initialized`

Notification (no `id`, no response).

### `tools/list`

Returns the catalogue in §4.

### `tools/call`

```jsonc
// request
{"jsonrpc":"2.0","id":7,"method":"tools/call",
 "params":{"name":"navigate","arguments":{"url":"https://example.com"}}}

// success — `isError:false`, `content` is the MCP content[] array
{"jsonrpc":"2.0","id":7,"result":{
   "content":[{"type":"text","text":"{\"ok\":true,\"url\":\"https://example.com/\"}"}],
   "isError":false,
   "_meta":{"duration_ms":823,"request_id":"req_..."}}}

// tool-level error — JSON-RPC result, isError:true (NOT a JSON-RPC error)
{"jsonrpc":"2.0","id":7,"result":{
   "content":[{"type":"text","text":"{\"code\":\"ssrf_blocked\",\"detail\":\"169.254.169.254 is not allowed\"}"}],
   "isError":true,
   "_meta":{"duration_ms":12,"request_id":"req_..."}}}
```

Protocol-level errors (bad JSON, unknown method, bad args) use the JSON-RPC
error envelope with codes:

| Code | Meaning |
|---|---|
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |

---

## 4. Tool catalogue (v0.1.0)

Every tool returns a JSON-encoded string inside `content[0].text`. The integrator
should `JSON.parse` it. Schemas below are the **parsed** result shape.

Common error codes (returned with `isError:true`):

| code | meaning |
|---|---|
| `ssrf_blocked` | URL points at private / metadata IP and host is not in allowlist |
| `captcha_required` | Page is showing a captcha challenge; agent must escalate |
| `session_timeout` | Per-session hard cap (30 min) reached; next call will get a fresh session |
| `chromium_crashed` | Underlying Chromium died; the pool will recreate on next call |
| `not_attached` | No active tab in the session — call `new_tab` first |
| `navigation_failed` | `Page.navigate` returned an error frame |
| `element_not_found` | Selector matched no nodes |
| `timeout` | Wait helper exceeded the supplied `timeout` seconds |
| `js_error` | `js()` expression threw |
| `bad_args` | Validation failed on tool arguments |
| `internal_error` | Bug in the harness service — should be rare; check logs |

### Tools

| Name | Args | Result |
|---|---|---|
| `navigate` | `{url: string, new_tab?: bool = false, wait_for_load?: bool = true, timeout?: number = 15}` | `{ok: true, url: string, title: string}` |
| `click` | `{x: number, y: number, button?: "left"\|"right"\|"middle" = "left", clicks?: number = 1}` | `{ok: true}` |
| `type` | `{text: string}` | `{ok: true}` |
| `fill` | `{selector: string, text: string, clear_first?: bool = true, timeout?: number = 0}` | `{ok: true}` |
| `press_key` | `{key: string, modifiers?: number = 0}` | `{ok: true}` |
| `scroll` | `{x: number, y: number, dy?: number = -300, dx?: number = 0}` | `{ok: true}` |
| `screenshot` | `{full_page?: bool = false, max_dim?: number\|null = null}` | `{mime: "image/png", base64: string}` |
| `extract_text` | `{selector?: string = "body", max_chars?: number = 8000}` | `{text: string, truncated: bool}` |
| `extract_html` | `{selector?: string = "html", max_chars?: number = 64000}` | `{html: string, truncated: bool}` |
| `page_info` | `{}` | `{url, title, w, h, sx, sy, pw, ph}` or `{dialog: {...}}` |
| `list_tabs` | `{include_internal?: bool = false}` | `{tabs: [{targetId, title, url}]}` |
| `switch_tab` | `{target_id: string}` | `{ok: true, session_id: string}` |
| `new_tab` | `{url?: string = "about:blank"}` | `{target_id: string, url: string}` |
| `close_tab` | `{target_id?: string}` (defaults to current) | `{ok: true}` |
| `wait_for_load` | `{timeout?: number = 15}` | `{loaded: bool}` |
| `wait_for_element` | `{selector: string, timeout?: number = 10, visible?: bool = false}` | `{found: bool}` |
| `wait_for_network_idle` | `{timeout?: number = 10, idle_ms?: number = 500}` | `{idle: bool}` |
| `js` | `{expression: string, await_promise?: bool = true}` | `{value: any}` — `any` is whatever the expression returned (must be JSON-serializable; coerce client-side) |
| `upload_file` | `{selector: string, paths: string[]}` (paths are resolved server-side against the per-agent profile dir) | `{ok: true}` |
| `http_get` | `{url: string, headers?: object, timeout?: number = 20}` | `{status: number\|null, body: string, truncated: bool}` (status is `null` when routed via the `fetch-use` proxy — that path returns body only) |
| `cdp` | `{method: string, params?: object}` | `{result: any}` — raw CDP escape hatch |
| `run_skill` | `{name: string, args?: object = {}}` | `{ok: true, return_value: any, stdout: string}` |
| `list_skills` | `{}` | `{skills: [{name, path, description?}]}` |
| `session_info` | `{}` | `{org_id, agent_id, started_at, idle_at, ttl_seconds, chrome_pid}` |
| `release_session` | `{persist?: bool = true}` | `{ok: true, persisted: bool}` — flushes profile to R2 and kills Chromium (next call creates a fresh session) |

### `navigate` semantics (most-asked questions)

- If the session has no real tab (just attached, or last tab was closed),
  `navigate` implicitly opens a new tab. Agents don't need to call `new_tab`
  first.
- `wait_for_load: true` polls `document.readyState == 'complete'` up to
  `timeout` seconds and returns whether it succeeded — the call **does not
  error** on timeout (`{ok: true, ...}` is still returned). Use
  `wait_for_element` if you need to assert.
- SSRF is checked **before** navigation. The check resolves the hostname and
  rejects RFC1918, loopback, link-local, `169.254.169.254`, and the IPv6
  equivalents (`fc00::/7`, `::1`, `fe80::/10`). To allow internal company
  tools, set env `BROWSER_HARNESS_ALLOWED_HOSTS=admin.acme.internal,*.tools.acme.com`.

### `run_skill` semantics

A skill is a Python file (`*.py`) under
`/var/lib/aki/browser-harness/skills/<org_id>/<agent_id>/` or the global
fallback `/var/lib/aki/browser-harness/skills/_shared/`. The skill is exec'd in
a namespace where:

- All browser-harness helpers are pre-imported (`navigate`, `click_at_xy`,
  `js`, `cdp`, `capture_screenshot`, `page_info`, etc.). These call **this
  agent's** session.
- The `args` dict is exposed as `args`.
- The skill assigns its return value to `result`. If it doesn't,
  `return_value` will be `null`.
- Captured stdout/stderr is returned as a single `stdout` string (≤ 16 KiB).

Failures inside the skill surface as `{code: "skill_error", detail: "..."}`
with the traceback's last frame.

---

## 5. Session lifecycle (what the integrator should know)

- Sessions are **lazy**: the first `tools/call` for a new `(org_id, agent_id)`
  creates the Chromium process. Cold start is ~2–4s on the smoke-test box.
- Sessions are **sticky**: subsequent calls within 10 min of idle reuse the
  same Chromium + per-agent profile.
- Sessions are **reaped** after 10 min of idle or 30 min total wall-clock,
  whichever comes first. Reaping persists the profile to R2 (key
  `<org_id>/<agent_id>/profile.tar.gz`).
- Sessions are **resumed** from R2 on re-creation, so cookies / localStorage /
  IndexedDB persist across the gap.
- Sessions are **per-agent**, not per-org. Two agents in the same org get
  two isolated profiles.

### Horizontal scaling

The pool's state is in-memory. To scale beyond one harness process, the load
balancer in front of the service **must** be sticky-routed on the tuple
`(X-Aki-Org-Id, X-Aki-Agent-Id)` (use the concatenation as the hash key). A
mis-routed request will silently spawn a duplicate Chromium with a stale
profile copy from R2 — correct but wasteful, and you'll burn 2× memory until
one is reaped.

---

## 6. Registration in `materialize.py`

Suggested addition to `materialize_mcp_servers()` for any org that has at
least one `connection.config.source == "browser_harness"`:

```python
if has_browser_harness and settings.browser_harness_url and settings.browser_harness_api_key:
    servers.append({
        "name": "browser",
        "transport": "http",
        "url": f"{settings.browser_harness_url}/mcp",
        "headers": {
            "Authorization": f"Bearer {settings.browser_harness_api_key}",
            "X-Aki-Org-Id": str(org_id),
            # X-Aki-Agent-Id is injected per-call by Hermes since one org has
            # N agents — see services/agent for how Hermes templates it.
        },
    })
```

The two new settings on `Settings`:

```python
browser_harness_url: str | None = None              # e.g. "http://browser-harness.aki.internal:7900"
browser_harness_api_key: str | None = None          # shared secret matching service env
```

The `X-Aki-Agent-Id` header is **per-call**, not per-org, so the gateway in
`services/api` is responsible for injecting it before forwarding to the MCP
endpoint. The harness rejects requests without it.

---

## 7. Stability / change policy

- Tool names, argument names, and result keys are SemVer-stable within the
  major version. Adding new tools / new optional args is a minor bump.
- Adding new error codes is a **minor** bump (clients should treat unknown
  codes as fatal-for-this-call).
- Changes to the auth header set, URL shape, or `tools/list` removals are a
  **major** bump.

Anything not documented here is internal and may change without notice.
