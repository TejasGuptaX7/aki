# Aki Architecture

> Source of truth for system design. Update this when decisions change.
> Last reviewed: 2026-05-16.

## 1. North star

**Aki is Hermes/OpenClaw for companies.** OpenClaw proved demand for personal
local-first agents; Aki packages that experience for organizations with the
trust and isolation enterprises require:

- per-org isolated agent runtime
- centralized OAuth + connector management via Composio
- hash-chained audit of every tool call + completion
- a unified product surface across many tools

The moat is **trust + multi-tenancy**, not orchestration capability — Hermes
already provides subagents, MCP, cron, skills, and memory.

## 2. Topology

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          Browser (Next.js 16, apps/web)                     │
│                          Landing only today; chat/connect UI later          │
└──────────────────────────────────────┬─────────────────────────────────────┘
                                       │  Clerk JWT (org_id claim)
                                       ▼
                  ┌──────────────────────────────────────┐
                  │   services/api  (FastAPI)            │
                  │ ─ Clerk JWT verify + dev bypass      │
                  │ ─ RLS GUC per request                │
                  │ ─ /webhooks/clerk                    │
                  │ ─ /connections/oauth/{start,callback}│
                  │ ─ /v1/chat/completions  (SSE proxy)  │
                  │ ─ /audit  (hash-chained log)         │
                  │ ─ /me, /health                       │
                  └────────┬───────────────────┬─────────┘
                           │                   │
              ┌────────────▼──────┐   ┌────────▼───────────────────┐
              │  Postgres + pgvec │   │ Per-org Hermes container   │
              │  (Neon)           │   │ aki-hermes:0.13.0          │
              │  RLS by org_id    │   │ - OpenAI-compat API server │
              │  hash-chain audit │   │ - hibernates @ 15min idle  │
              └───────────────────┘   └────┬───────────────┬───────┘
                                           │ MCP (HTTP)    │ (built-in tools:
                                           ▼               │  execute_code,
                                ┌──────────────────────┐   │  browser, etc.)
                                │  Composio tool router │
                                │  → 500+ SaaS apps     │
                                └──────────────────────┘
```

## 3. Tenancy model

- **Single org per user** for v1. `users.organization_id` is a direct FK.
- Org auto-provisioned on first signup via Clerk webhook (svix-verified). Name
  defaults to email domain. Same transaction creates a default `org_memory`
  row and PATCHes Clerk `user.public_metadata.aki_org_id` so the `aki` JWT
  template can populate the `org_id` claim on next sign-in.
- Every tenant-scoped table denormalizes `organization_id` and indexes by it.
  One RLS policy per table:
  `using (organization_id = current_setting('app.org_id')::uuid)`.
- API runs `SELECT set_config('app.org_id', :oid, true)` from the verified
  Clerk claim in a request-scoped session — see `app/db.py::session_for_org`.
  (Note: `SET LOCAL` doesn't accept bound params on asyncpg; `set_config` does.)

Upgrade path to multi-org: add a `memberships(user_id, organization_id, role)`
table, deprecate `users.organization_id`, add `X-Org-Id` header switching.

## 4. Auth

- **Production**: Clerk JWT (`Authorization: Bearer …`). The `aki` JWT
  template injects `org_id` from `user.public_metadata.aki_org_id`. Verified
  RS256 against Clerk JWKS.
- **Dev**: if `APP_ENV=dev` AND `ALLOW_DEV_AUTH_BYPASS=true`, an
  `X-Dev-Org-Id` header skips JWT verification. Two checks so a single env
  misconfiguration in prod can't grant access.
- Webhook signing verified via svix.

## 5. Agent runtime (Hermes 0.13)

- **PyPI version**: `hermes-agent==0.13.0`. (Nous publishes a different
  version line to PyPI than to GitHub; v0.4.0 was a GitHub sub-version that
  never reached PyPI. Track PyPI's line until they stabilize.)
- Per-org Docker container (`aki-hermes:0.13.0`) bootable on demand. State at
  `${HERMES_DATA_DIR}/<org_id>/` — defaults to `~/.aki/hermes` for dev,
  override in prod.
- Lifecycle in `app/agent_runtime.py`:
  - `ensure_running(db, org_id)` — idempotent cold-start (~10s) with an
    async lock per org; reuses warm containers.
  - `hibernation_loop()` — background asyncio task in FastAPI lifespan;
    stops containers idle > `HERMES_IDLE_MINUTES` (default 15).
  - `reap_orphans()` — on startup, kills any `aki-hermes-*` container not
    in the in-memory registry (handles uvicorn crashes that skipped
    lifespan shutdown).
- Hermes exposes its **OpenAI-compatible API** at port 8080 inside the
  container; we map to a random host port per org. Auth via a per-container
  `API_SERVER_KEY` the proxy sends as Bearer.
- Inference: **OpenAI direct** via Hermes' `provider: custom` +
  `base_url: https://api.openai.com/v1`. Hermes has no first-class `openai`
  provider — they treat OpenAI as a model on OpenRouter/Nous Portal. Custom
  provider works because OpenAI's API is OpenAI-compatible (definitionally).
  Model selected via `HERMES_MODEL_NAME` env, default `gpt-5`.

## 6. Connectors — everything is an MCP server

We **dropped** the original three-layer abstraction (Hermes-native +
Composio + custom MCP). The control plane never executes tool calls itself —
Hermes does, via MCP. So the connector layer's only job is to translate
`connections` rows into the per-org `mcp_servers` dict in `hermes.config.yaml`.

- `app/connectors/materialize.py::materialize_mcp_servers(db, org_id)` is the
  single function that does this.
- The `connections` table has `(provider, config, status, scopes, …)` with
  `config.source ∈ {"composio", "custom"}`. Adding a new source (Nango,
  Pipedream, …) requires no schema change — only a branch in materialize.

Composio specifically:
- `POST /api/v3/connected_accounts/link` for OAuth initiation
- `POST /api/v3/tool_router/session` returns a per-user MCP URL we point
  Hermes at; the URL is session-scoped (`session.mcp.url`)
- Per-toolkit Auth Config IDs (`ac_…`) live in settings, one env var per
  toolkit enabled. See `app/composio_client.py::auth_config_id_for`.

Future enterprise path: when a customer asks for self-host, swap to Nango
by changing only `materialize_mcp_servers`. No other code or schema touches.

## 7. Memory

- Canonical store: Postgres `org_memory` table (key/value with versioning).
- Each Hermes process is meant to hydrate its `MEMORY.md` from `org_memory`
  on boot via a small sync skill. **Not yet wired** — Hermes 0.13 has its
  own memory system; integration is a Phase 3+ item.
- `USER.md` per (org, user) lands when memberships does.

## 8. Retrieval

**Deferred.** Hermes 0.13's built-in document attachment is enough for v1.
We'll build the pgvector + BM25 + RRF + ACL-snapshot pipeline only after
customers show failure modes the built-in attachment can't solve.

When we do build it:
- Hybrid: pgvector cosine + tsvector BM25 with reciprocal rank fusion,
  reranked by a cross-encoder.
- ACL snapshot stored on each `source` row at index time
  (`acl_principals jsonb`); query-time check intersects current principals
  against the snapshot AND the live provider ACL (cached, short TTL).
- Embeddings: OpenAI `text-embedding-3-small` (1536d). Upgrade path to
  Voyage `voyage-3` later; dim change requires a re-embed migration.

## 9. Audit

- `audit_log` is **hash-chained from row one**:
  - `content_hash = sha256(canonical_json({org, actor, action, target, payload, prev}))`
  - `prev_hash` = previous row's `content_hash` within `(organization_id)`
- Per-org serialization enforced with `pg_advisory_xact_lock` so concurrent
  inserts can't race the prev_hash.
- Append-only via Postgres trigger; UPDATE/DELETE raise an exception at the
  DB level. App role has no grant either way.
- Three event types written today, all by the chat proxy:
  - `chat.start` — at request entry, payload `{bytes}`
  - `chat.tool_call` — one per `event: hermes.tool.progress` SSE chunk
    tapped inline from the streaming response (no separate event endpoint
    needed); payload includes `{tool, status, label, container_id}` where
    `label` carries the tool's input args (e.g. the actual Python code for
    `execute_code`)
  - `chat.complete` — when stream closes, payload includes `{usage,
    duration_ms, tool_calls, model, cost_usd}`. Cost from the small per-model
    pricing table at `app/pricing.py`.
- `GET /audit` returns paginated rows (scoped by RLS to the principal's
  org) with all hash-chain fields so clients can verify the chain locally.

## 10. Phasing — shipped vs. open

| Phase | Status      | Scope                                                                                   |
| ----- | ----------- | --------------------------------------------------------------------------------------- |
| 2a    | ✅ shipped  | Clerk + Composio + Neon tenancy plumbing                                                |
| 2b    | ✅ shipped  | Per-org Hermes container, OpenAI inference, SSE proxy                                   |
| 2c    | ✅ shipped  | SSE-tap audit, GET /audit, cost tracking, Clerk metadata round-trip, orphan reaper      |
| 2c+   | open        | Slack OAuth via Composio + DM delivery on long-task completion                          |
| 3     | open        | Retrieval pipeline if and when Hermes' built-in attachment fails customers              |
| 4     | open        | RBAC granularity (memberships, per-resource ACL), admin console, per-user `USER.md`     |
| 5     | open        | Billing (Stripe), usage metering off the cost_usd field already in audit                |
| Web   | partial     | Landing (Glyph II direction) shipped; chat, /connect, audit viewer not started          |

## 11. Operational details

- **Deploy target**: Railway for `services/api` and per-org Hermes containers.
  Revisit Fly/Modal/K8s when per-org density justifies it.
- **Per-process workspace storage**: local volume mount today; S3-backed
  FUSE later for elastic scaling.
- **Rate limits**: `slowapi` in-memory backend, 120/min webhooks, 30/min OAuth.
  Multi-worker prod needs a Redis storage_uri (documented in `app/limits.py`).
- **CORS**: empty list by default (no browser clients). Set `CORS_ORIGINS`
  as CSV in env. Custom validator accepts CSV without JSON-bracketing.
- **Errors**: JSON 500 with `request_id`; every response carries
  `X-Request-Id` via middleware.
- **Secret hygiene**: `.env` ignored; pre-commit grep for `ak_*`, `sk_*`,
  `whsec_*`, `npg_*`, `pretty-boxer`, `wandering-wildflower`,
  `trycloudflare` before each push.

## 12. Open decisions for future Aki

- **Per-user vs per-org OAuth**: currently org-scoped (first person to
  "Connect Gmail" connects their personal account for the org). Adding
  `connections.user_id` and scoping by user in `materialize_mcp_servers`
  is one column + one filter.
- **Composio API key isolation**: Composio's MCP URL requires our master
  `x-api-key` in headers — Hermes (per-org container) has it. Acceptable
  for SMB. Mid-market may want Composio sub-keys or a Nango swap.
- **Hermes version cadence**: Nous publishes weekly-ish. We pinned 0.13.0;
  re-pin when a release adds something we want (e.g. better caching).
- **Embedding upgrade trigger**: define recall@10 threshold on a labeled
  eval set before swapping to Voyage.
