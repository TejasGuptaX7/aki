# Aki

Aki is the company-grade agent platform — Hermes/OpenClaw for organizations.
Each org gets its own isolated Hermes runtime, wired into the company's tools
(Composio long-tail + Hermes native plugins + custom MCP), with the trust
layer (auth, RBAC, audit, central memory) built in.

## Monorepo layout

```
apps/
  web/              # Next.js 16 marketing + product UI (Clerk auth, shadcn)
services/
  api/              # FastAPI control plane: auth, orgs, connectors, memory, audit
  agent/            # Hermes per-org runtime — pinned to v0.4.0, OpenAI-compatible
packages/
  shared/           # cross-service types and contracts (TS)
docs/
  architecture.md   # source-of-truth for system design + decisions
```

## Quick start

```bash
cp .env.example .env                          # fill keys as you go
cd apps/web    && npm install && npm run dev  # → http://localhost:3000
cd services/api && pip install -r requirements.txt && uvicorn app.main:app --reload  # → :8000
```

## Decisions locked in

- **Single org per user** for v1. `users.organization_id` is a direct FK; promote to a memberships join later without API breakage.
- **Per-org Hermes process** (containerized, hibernation, stateless gateway in front).
- **Hybrid connectors**: Composio for the long tail, Hermes native plugins (Linear/GitHub/Gmail/Calendar/Canva) for depth, custom MCP/OpenAPI for internal tools.
- **Central memory** lives in Postgres; each Hermes process hydrates `MEMORY.md` per-process at boot.
- **Embeddings**: OpenAI `text-embedding-3-small` (1536d). Upgrade later if recall warrants.
- **Inference**: Anthropic under Hermes by default.
- **Audit**: hash-chained from row one (`content_hash`, `prev_hash`) for tamper-evident logs.

See `docs/architecture.md` for the full picture.
