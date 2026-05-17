# Aki Architecture

> Source of truth for system design. Update this when decisions change.
> Last reviewed: 2026-05-17.

## 1. North star

**Aki is Hermes/OpenClaw for companies.** OpenClaw proved demand for personal
local-first agents; Aki packages that experience for organizations:

- many named, long-lived agents per company (e.g. "Aki Sales", "Aki Recruiting")
- per-agent isolated runtime (Hermes profile per agent inside a per-org container)
- white-label OAuth connectors via Pipedream + Arcade
- self-hosted browser harness for novel sites + autonomous signup
- three-tier consent model (auto / ask / never-money) with real blocking enforcement
- hash-chained audit + per-org rate limits + platform circuit breaker

The moat is **trust + multi-tenancy + freeform agent factory**, not orchestration
capability — Hermes already provides MCP, cron, skills, memory.

## 2. Topology

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Browser (Next.js 16, apps/web)                       │
│            landing · /agents · /chat/[agentId] · /connect · /audit ·          │
│                  /approvals · /docs · /pricing · /trust                       │
└─────────────────────────────────────────┬────────────────────────────────────┘
                                          │  Clerk JWT (org_id claim)
                                          ▼
                  ┌──────────────────────────────────────────┐
                  │    services/api   (FastAPI control plane) │
                  │                                          │
                  │  /me  /agents  /connections  /audit      │
                  │  /approvals  /v1/chat/completions        │
                  │  /webhooks/clerk                         │
                  │  /agent_internal/mcp  (internal)         │
                  │                                          │
                  │  - Clerk JWT verify + dev-bypass         │
                  │  - RLS GUC per request                   │
                  │  - per-org daily caps + circuit breaker  │
                  │  - hash-chained audit                    │
                  │  - per-org docker spawn (Path B, ADR-0001)│
                  └─────┬──────────────┬─────────────────────┘
                        │              │
        ┌───────────────▼─────┐   ┌────▼─────────────────────────────────┐
        │  Postgres + pgvec   │   │  Per-org Docker container             │
        │  (Neon)             │   │  aki-hermes:0.13.0                    │
        │  RLS by org_id      │   │                                       │
        │  hash-chain audit   │   │   supervisor.py (PID 1, :8080)        │
        │                     │   │     ├─ reads manifest.json            │
        │  agents             │   │     ├─ spawns hermes profiles         │
        │  agent_memory       │   │     └─ routes /v1/* by X-Aki-Agent-Id │
        │  connections        │   │                                       │
        │  approvals          │   │   hermes -p <aki>        :9001        │
        │  rate_limits        │   │   hermes -p <aki-sales>  :9002        │
        │  audit_log          │   │   …                                   │
        └─────────────────────┘   │   each profile = own HERMES_HOME,     │
                                  │   own MEMORY/USER, own MCP config     │
                                  └──┬──────────────┬───────────────────┬─┘
                                     │              │                   │
                          ┌──────────▼───┐  ┌───────▼──────┐  ┌─────────▼──────┐
                          │  Pipedream    │  │  Arcade.dev  │  │ services/      │
                          │  Connect MCP  │  │  MCP         │  │ browser-harness│
                          │  (~3k apps)   │  │  (top-20)    │  │ (self-hosted   │
                          │               │  │              │  │  Chrome pool)  │
                          └───────────────┘  └──────────────┘  └────────────────┘
```

## 3. Tenancy model

- **Two-level isolation**: organization (the company, hard tenant boundary)
  and agent (one of many named runtimes inside an org).
- **Single org per user** for v1. `users.organization_id` is a direct FK.
  Multi-org per user lands when we add a `memberships` join table.
- **Many agents per org**. `agents` table; created via `POST /agents` or
  default "Aki" provisioned by the Clerk webhook.
- Org auto-provisioned on first signup via Clerk webhook (svix-verified).
  Name defaults to email domain. Same transaction creates the default Aki
  agent + an initial `agent_memory` row + PATCHes Clerk
  `user.public_metadata.aki_org_id` so the JWT template populates `org_id`.
- Every tenant-scoped table denormalizes `organization_id` and indexes by
  it. RLS scopes by org only — `using (organization_id = current_setting('app.org_id', true)::uuid)`.
  Cross-agent isolation inside an org is enforced by application queries
  (`WHERE agent_id = X`), not RLS. Bugs there leak across one company's
  own agents — a UX bug, not a tenancy breach.

## 4. Auth

- **Production**: Clerk JWT (`Authorization: Bearer …`). The `aki` JWT
  template injects `org_id` from `user.public_metadata.aki_org_id`.
  Verified RS256 against Clerk JWKS. Falls back to DB lookup if the
  claim is missing (e.g. stale JWT after metadata change).
- **Dev**: if `APP_ENV=dev` AND `ALLOW_DEV_AUTH_BYPASS=true`, an
  `X-Dev-Org-Id` + `X-Dev-User-Id` header pair skips JWT verification.
- **Agent → control plane**: per-agent service token (sha256-hashed at
  rest in `agents.service_token_hash`, plaintext lives in the per-agent
  workspace's `config.yaml`). Used only for `/agent_internal/*` routes.
- **Clerk webhook**: svix-verified.

## 5. Agent runtime (Hermes 0.13)

- **PyPI version**: `hermes-agent==0.13.0`. (Nous publishes a different
  version line to PyPI than to GitHub; v0.4.0 was a GitHub sub-version
  that never reached PyPI. Track PyPI's line.)
- **One Docker container per organization** (`aki-hermes-<org_id>`).
  Per-org workspace mounted at `/opt/data` from
  `${HERMES_DATA_DIR}/<org_id>/`.
- **N Hermes profiles per container, one per agent**. Each profile is
  its own subprocess with its own `HERMES_HOME` (the agent's workspace
  subdir), its own `MEMORY.md`/`USER.md`, its own SQLite session DB.
  Spawned by `hermes profile create <agent_id> && hermes -p <agent_id> gateway run`.
- **supervisor.py** runs as PID 1 inside the container:
  - reads `/opt/data/manifest.json` (the control plane writes it)
  - spawns one Hermes profile per agent on internal ports 9001+
  - serves `:8080` as a single HTTP entrypoint; routes `/v1/*` by
    `X-Aki-Agent-Id` header to the right profile's internal port
  - `/control/health` reports per-profile readiness;
    `/control/reload` re-reads the manifest and converges processes
  - byte-for-byte SSE passthrough so the chat audit-tap works
- **Lifecycle** in `services/api/app/agent_runtime.py`:
  - `ensure_org_container(db, org_id)` — idempotent cold-start (~10s)
    with async lock per org; reuses warm containers
  - `ensure_agent_loaded(db, org_id, agent_id)` — guarantees the
    profile is loaded; updates the manifest and reloads supervisor if
    the agent is new
  - `hibernation_loop()` — stops containers idle > `HERMES_IDLE_MINUTES`
    (default 15)
  - `reap_orphans()` — on startup, kills `aki-hermes-*` containers
    not in the in-memory registry
- **Deploy target** for `services/api`: single VM with docker.sock per
  ADR-0001 (`infra/decisions/0001-deploy-target.md`). Fly Machines API
  client deferred until per-org density justifies it.
- **Inference**: OpenAI direct via Hermes' `provider: custom` +
  `base_url: https://api.openai.com/v1`. Model selected via
  `HERMES_MODEL_NAME` env, default `gpt-5`.

## 6. Connectors

All connectors surface to Hermes via MCP. The control plane never
executes tool calls itself; `materialize_mcp_servers` translates
`connections` rows into the per-agent `mcp_servers` config that Hermes
loads at profile start.

### Source kinds

| `config.source` | What | When |
|---|---|---|
| `pipedream` | Pipedream Connect MCP — ~3,000 apps, white-label OAuth | Long-tail SaaS |
| `arcade` | Arcade.dev MCP — agent-native URL Elicitation auth | Top-20 high-value tools (Gmail send, Slack post, etc.) |
| `browser_harness` | Self-hosted services/browser-harness | Novel sites, autonomous account signup |
| `browser_use` | Browser Use Cloud | Fallback for deterministic browser ops |
| `custom` | BYO MCP URL + headers | Internal company tools |
| `composio` *(legacy)* | Composio MCP | Pre-Pipedream rows; silently skipped — `composio_client.py` deleted in phase 3d. User re-OAuths via Pipedream to migrate. |

### Per-agent scoping

- `connection.agent_id IS NULL` → org-wide, every agent sees it
- `connection.agent_id = X` → only agent X sees it
- A given agent's MCP list is the **union** of (org-wide ∪ its own)

`materialize_mcp_servers(db, org_id, agent_id, agent_service_token=…)`
emits separate MCP entries for org-wide vs per-agent Pipedream/Arcade
external_user_ids — Hermes sees both as independent servers.

### Pipedream Connect specifics

- Auth: OAuth `client_credentials` → short-lived JWT (cached, single-flight
  refresh in `app/pipedream_client.py`)
- Header: `X-PD-Environment: development | production` on every API call
- External user id: `str(org_id)` (org-wide) or `f"{org_id}:{agent_id}"`
  (per-agent)
- Frontend flow: `POST /connections/pipedream/connect-token` returns a
  token + a `connect_link_url`; frontend either uses the Pipedream JS
  SDK (modal) or redirects to the hosted link. On success the frontend
  POSTs `/connections/pipedream/record` with the new account_id.

### Browser harness contract

See `services/browser-harness/PROTOCOL.md`. Wire shape: MCP HTTP at
`${BROWSER_HARNESS_URL}/mcp`, Bearer + `X-Aki-Org-Id` + `X-Aki-Agent-Id`
headers. Per-(org, agent) Chromium sessions; profile state persisted to
R2/S3 between sessions.

## 7. Consent (three tiers)

Every tool the agent can call is classified into one of three tiers by
`app/consent.py::tier_for_tool(name)`:

| Tier | Name | Behavior |
|---|---|---|
| 1 | AUTO | Execute + audit. Read ops, navigation, lookups. |
| 2 | ASK | Agent must call `request_approval` first and wait for user yes/no. External email, public posts, account signups, destructive ops. |
| 3 | FORBID | Never reachable. Money-touching tools. Filtered out at materialize time (not yet enforced at MCP-proxy level; v1 relies on system prompt + OAuth scope absence). |

### Real enforcement for tier 2

`services/api/app/routes/agent_internal.py` exposes a Streamable HTTP
MCP server at `/agent_internal/mcp` with one tool: `request_approval`.
Every agent's per-profile config includes this MCP server with the
agent's service token in headers. The system prompt instructs the
agent to call `request_approval(kind, tool, args, summary)` before any
tier-2 tool. The tool implementation creates an `approvals` row,
long-polls `/approvals/{id}/wait` until the user approves/denies or
the request expires, and returns `{approved: bool, status, ...}` to
the agent.

UI: `/approvals` inbox + per-row Approve/Reject buttons.

## 8. Rate limits + circuit breaker (no-billing abuse defense)

Free during beta + no payment integration means a single abuser can burn
through Pipedream/Arcade/Browser Use credits in a weekend. Defense:

- **Per-org daily caps**: `rate_limits` table, atomic UPSERT increment.
  - `actions_count` — chat turns per day (default 500)
  - `browser_seconds` — browser harness time per day (default 3600 = 60 min)
  - `llm_cents` — LLM spend per day (default 5000 = $50)
  - Enforced before any expensive work (`enforce_daily_cap`); recorded
    after success (`record_usage`). Reset at UTC midnight.
- **Global circuit breaker**: total platform `llm_cents` for today vs
  `platform_daily_spend_cap_cents` (default 50000 = $500). Pauses NEW
  signups when breached; existing users unaffected. Enforced in
  `/webhooks/clerk` before org provisioning; svix retries when we're
  back under budget.

All defaults are env-tunable (see `.env.example`).

## 9. Audit

- `audit_log` is **hash-chained from row one**:
  - `content_hash = sha256(canonical_json({org, actor, action, target, payload, prev}))`
  - `prev_hash` = previous row's `content_hash` within `(organization_id)`
  - `agent_id` column added in migration 0003 but NOT in the hash input —
    historical rows existed without it; changing the hash schema would
    break chain verification. `agent_id` is queryable metadata.
- Per-org serialization via `pg_advisory_xact_lock` so concurrent inserts
  can't race.
- Append-only via Postgres trigger; UPDATE/DELETE raise an exception.
- Events written:
  - `org.create`, `agent.create/update/delete`
  - `chat.start`, `chat.tool_call` (per-tool tier classification recorded),
    `chat.complete` (model + usage + cost_usd)
  - `approval.request` (by agent), `approval.create` (by user),
    `approval.approved`, `approval.denied`
  - `oauth.*`, `webhook.*` (org-level, NULL agent_id)
- `GET /audit?agent_id=X&limit=N` paginated, scoped by RLS.

## 10. Memory

- Canonical store: Postgres `agent_memory` table (per-agent namespace;
  replaces the v1 `org_memory` table). Composite key `(agent_id, key)`.
- Each Hermes profile hydrates its `MEMORY.md` from `agent_memory` on
  boot via a sync skill. **Not yet wired in v1** — Hermes 0.13 has its
  own filesystem-backed memory under each profile's `HERMES_HOME`,
  which survives container restarts via the per-org workspace volume.
- `USER.md` per (org, user) lands when memberships does.

## 11. Retrieval

**Deferred.** Hermes 0.13's built-in document attachment is enough for
v1. We'll build the pgvector + BM25 + RRF + ACL-snapshot pipeline only
after customers show failure modes the built-in attachment can't solve.

When we do build it:
- Hybrid: pgvector cosine + tsvector BM25 with reciprocal rank fusion,
  reranked by a cross-encoder.
- ACL snapshot stored on each `source` row at index time; query-time
  check intersects current principals against the snapshot AND the live
  provider ACL.
- Embeddings: OpenAI `text-embedding-3-small` (1536d).

## 12. Operational

- **Production deploy target**: ADR-0001. `services/api` → single VM with
  docker.sock (Railway / Hetzner / EC2). `services/browser-harness` →
  Fly Machines. `apps/web` → Vercel.
- **Per-org workspace storage**: local volume on the API host. S3-backed
  FUSE if/when we move to multi-host.
- **Rate limits**: `slowapi` in-memory backend for webhooks + OAuth.
  Multi-worker prod needs a Redis storage_uri (`app/limits.py`).
- **CORS**: empty list by default. Set `CORS_ORIGINS` as CSV.
- **Errors**: JSON 500 with `request_id`; every response carries
  `X-Request-Id` via middleware.
- **Secret hygiene**: `.env` ignored. Pre-commit grep for known prefixes
  (`pk_live_`, `sk_live_`, `whsec_`, `npg_`, `pcs_`, `arc_`, `pd_pat_`,
  `xoxb-`, `xoxp-`) before each push.

## 13. Phasing — shipped vs. open

| Phase | Status | Scope |
|---|---|---|
| 1 | ✅ | Marketing waitlist |
| 2a | ✅ | Clerk + Composio + Neon tenancy plumbing (Composio sunset in 3d) |
| 2b | ✅ | Per-org Hermes container, OpenAI inference, SSE proxy |
| 2c | ✅ | SSE-tap audit, GET /audit, cost tracking, orphan reaper |
| 3a | ✅ | Multi-agent core (schema, runtime, profile-per-agent, supervisor) |
| 3b | ✅ | Safety floor (consent tiers, rate limits, approvals API) + Pipedream/Arcade clients + materialize rewrite |
| 3c | ✅ | request_approval real tier-2 enforcement (internal MCP + service tokens) |
| 3d | ✅ | Composio sunset (code deletion; legacy DB rows silently skipped) |
| 4 | open | Slack DM listener (`/webhooks/slack`) — pending Slack app registration |
| 5 | open | Production deploy (per ADR-0001) + observability (Sentry, Grafana dashboards) |
| 6 | open | Onboarding email lifecycle, marketing polish, real OG image |
| 7 | open | Billing (Stripe), usage metering off `cost_usd` |
| 8 | open | Retrieval pipeline if/when Hermes built-in attachment fails customers |
| 9 | open | RBAC granularity (memberships, per-resource ACL), admin console |
| 10 | open | Per-agent Slack bot users (today: one Aki bot per workspace, all agents share its identity) |

## 14. Open decisions for future Aki

- **Per-user vs per-org OAuth on Pipedream**. v1 supports both
  (`external_user_id` shape switches on `agent_id`). UI surfaces the
  toggle. Default org-wide unless the user picks an agent.
- **Hermes profile RAM cost**. Architecture assumes 5 profiles fit in
  a 2GB container. Measured 2 profiles + supervisor uses ~250MB RSS
  in dev — extrapolates fine, but re-validate at 5+ profiles before
  setting container size in prod.
- **Hermes version cadence**. Nous publishes weekly-ish. Pinned 0.13.0;
  re-pin when a release adds something we want (better caching, env
  interpolation in mcp_servers headers, etc.).
- **Approval timeout vs retry**. Current behavior: 10-minute TTL, agent
  gets `pending_timeout` if it waits the full 50s and no decision yet.
  Open: should the agent be able to RE-call wait with the same
  approval_id to extend, or always create a new approval row?
- **Embedding upgrade trigger**. Define recall@10 threshold on a labeled
  eval set before swapping to Voyage.
