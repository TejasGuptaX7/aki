# Aki / Hermes / Brain

Three products on one codebase:

- **Hermes** — per-department cloud agents. An employee files a brief
  ("post this job, screen resumes, book a calendar interview"); Hermes
  runs through the night on our infra and reports back. No laptop required.
- **Aki** — per-employee local desktop agent (Tauri tray, ⌘⇧Space chat,
  embedded `hermes-agent`). Automates the personal layer of an employee's
  workday. Lives on the laptop, not in the cloud.
- **Brain** — the shared, embedding-indexed, ACL-aware memory store both
  read from and write to. Exportable as JSONL for future Qwen fine-tuning.

The repo name stays `aki` (the org/program). Phase 1 reorients today's
single-product code to this three-product architecture.

## Monorepo layout

```
apps/
  web/              # Next.js 16 marketing + product UI (Clerk)
  aki-desktop/      # Tauri tray app — Phase 3
services/
  api/              # FastAPI control plane: auth, orgs, departments,
                    # connections, brain, jobs, devices, audit
  agent/            # Per-department Hermes container — pinned to 0.13.0
packages/
  shared/           # cross-service types and contracts (TS)
docs/
  architecture.md   # source-of-truth for system design + decisions
```

## Quick start

```bash
cp .env.example .env                           # fill keys as you go
cd apps/web    && npm install && npm run dev   # → http://localhost:3000
cd services/api && pip install -r requirements.txt && uvicorn app.main:app --reload  # → :8000
```

## Decisions locked in

- **Per-department Hermes** (containerized, idle-hibernated). Cold-start on
  job dispatch; tagged by `(org_id, department_id)`.
- **Per-employee Aki** desktop (Phase 3). Pairs to the cloud with an
  Ed25519 device JWT; syncs journal + notes into Brain.
- **Brain** is the canonical memory. Hybrid retrieval (pgvector cosine +
  Postgres tsvector BM25, fused with RRF). ACL principals snapshotted at
  ingest; intersection check after RRF. Sources include job summaries,
  chat turns, Aki journals, and imported docs.
- **Hybrid connectors**: Composio for the long tail, Hermes native plugins
  for depth, custom MCP/OpenAPI for internal tools.
- **Embeddings**: OpenAI `text-embedding-3-small` (1536d). Upgrade later if
  recall warrants.
- **Audit**: hash-chained from row one, append-only at the DB level. One
  chain per org; department lives in the `target` field.

See `docs/architecture.md` for the full picture.
