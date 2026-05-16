# Aki Architecture

> Source of truth for system design. Update this when decisions change.
> Last reviewed: 2026-05-15.

## 1. North star

**Aki is Hermes/OpenClaw for companies.** OpenClaw proved demand for personal
local-first agents; Aki packages that experience for organizations with the
trust and isolation enterprises require:

- per-org isolated agent runtime
- centralized OAuth + connector management
- RBAC, audit, retrieval permissioning
- a unified product surface across many tools

The moat is **trust + multi-tenancy**, not orchestration capability — Hermes
already provides subagents, MCP, cron, skills, and memory.

## 2. Topology

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Browser (Next.js)                              │
└──────────────────────────────────────┬─────────────────────────────────────┘
                                       │  Clerk session
                                       ▼
                  ┌──────────────────────────────────────┐
                  │   services/api  (FastAPI control)    │
                  │ ─ Clerk JWT verify                   │
                  │ ─ RLS GUC per request                │
                  │ ─ orgs, users, connectors, memory    │
                  │ ─ retrieval API, audit, billing      │
                  └────────┬───────────────────┬─────────┘
                           │                   │
              ┌────────────▼──────┐   ┌────────▼───────────┐
              │  Postgres + pgvec │   │ services/agent     │
              │  (Supabase)       │   │ Hermes per-org     │
              │  RLS by org_id    │   │ processes, OAI API │
              └───────────────────┘   └─────────┬──────────┘
                                                │ MCP / Composio
                                                ▼
                                       External tool surfaces
                                       (Gmail, Notion, Linear…)
```

## 3. Tenancy model

- **Single org per user** for v1. `users.organization_id` is a direct FK.
- Personal org auto-provisioned on first signup via Clerk webhook, same
  transaction as `users` insert. Name defaults to user name / email domain.
- Every tenant-scoped table denormalizes `organization_id` and leads its
  indexes with it. One RLS policy per table:
  `using (organization_id = current_setting('app.org_id')::uuid)`.
- API sets `SET LOCAL app.org_id = '<uuid>'` from the verified Clerk claim
  in a request-scoped session — see `app/middleware.py`.

Upgrade path to multi-org: introduce `memberships(user_id, organization_id,
role)`, deprecate `users.organization_id`, add `X-Org-Id` header switching.
Endpoints are already org-scoped under `/orgs/{org_id}/...` to make this a
non-breaking change.

## 4. Agent runtime (Hermes v0.4.0)

- Pinned version: **0.4.0** (Mar 23 2026 platform-expansion release).
- One containerized Hermes process per active org. Hibernates after N min
  idle, cold-starts on first request. State (memory, skills, tool grants)
  persists in Postgres and a per-org workspace dir mounted at
  `${HERMES_DATA_DIR}/<org_id>/`.
- A stateless **gateway proxy** in `services/api` sits in front of Hermes:
  - injects per-org auth / scopes
  - enforces RBAC and permission checks before tool calls reach Composio
  - records every tool call into `audit_log` (hash-chained)
- Hermes runs in OpenAI-compatible mode (`/v1/chat/completions`). The web app
  talks to the gateway, never to Hermes directly.
- Inference: Anthropic via Hermes' `hermes login anthropic` OAuth (or API key
  in dev). Model selection per-org via `hermes model`.

## 5. Connectors

Three layers under a unified `connections` UI:

| Layer            | Use for                                  | How                                   |
| ---------------- | ---------------------------------------- | ------------------------------------- |
| Hermes native    | Gmail, Calendar, GitHub, Linear, Canva   | First-party plugins, fastest path     |
| Composio MCP     | Everything else (Notion, Slack, …)       | Per-org Composio account, MCP servers |
| Custom (BYO MCP) | Internal tools (private MCP / OpenAPI)   | URL + auth header registration        |

The proxy enforces:
1. user has a grant for this connector (org-scoped)
2. requested scope matches granted scope
3. ACL snapshot stored at index time still permits the access

First connector wired after auth: **Gmail** (denser signal, easier eval).

## 6. Memory

- Canonical store: Postgres `org_memory` table (key/value with versioning).
- Each Hermes process hydrates its `MEMORY.md` from `org_memory` on boot,
  writes back via a small sync skill.
- `USER.md` per (org, user) — populated in a later phase when per-user
  context lands. For v1, all members share the org memory.

## 7. Retrieval

- Hybrid: pgvector cosine + tsvector BM25 with reciprocal rank fusion,
  reranked by a cross-encoder. Necessary for heterogeneous corpora
  (email + docs + issues).
- ACL snapshot stored on each `source` row at index time
  (`acl_principals jsonb`). Query-time check intersects current user/group
  principals against the snapshot **and** against the live provider ACL
  (cached, short TTL) to catch revocations.
- Embeddings: OpenAI `text-embedding-3-small` (1536d). Upgrade path to
  Voyage `voyage-3` later — dim change requires a re-embed migration.

## 8. Audit

- `audit_log` is **hash-chained from row one**:
  - `content_hash = sha256(jsonb_canonical(event))`
  - `prev_hash` = previous row's `content_hash` within `(organization_id)`
- Append-only via Postgres trigger; no `update`/`delete` grants for app role.
- Mirror to object storage later for tamper-evident archival without
  schema migration.

## 9. Phasing

| Phase | Scope                                                          |
| ----- | -------------------------------------------------------------- |
| 1     | Marketing site + waitlist (Resend)                             |
| 2     | Auth (Clerk), orgs, connectors UI, Gmail OAuth via Composio    |
| 3     | Retrieval: index Gmail → pgvector/BM25 → search-before-chat UI |
| 4     | Hermes per-org runtime + chat surface + audit log              |
| 5     | RBAC, admin console, per-user context layering                 |
| 6     | Billing (Stripe), usage metering                               |

## 10. Open questions

- Hermes deployment target: **Railway for v1** (already used for `services/api`).
  Revisit when per-org density makes Fly/Kubernetes attractive.
- Per-process workspace storage: local volume for v1, S3-backed FUSE later.
- Embedding upgrade trigger: define recall@10 threshold on a labeled eval
  set before considering Voyage swap.
