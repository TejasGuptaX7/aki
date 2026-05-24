# Aki Program — Comprehensive Build Plan
> Version: 1.0 | Date: 2026-05-24
> Based on: Full codebase audit + market research + enterprise architecture analysis

---

## 1. EXECUTIVE VISION

Build the **first enterprise-grade AI agent platform** that unifies:
- **Hermes** → Department-level cloud agents that work while you sleep
- **Aki** → Personal desktop agents that automate your daily workflow  
- **Brain** → Shared, embedding-indexed, ACL-aware memory that both use

**The moat**: Brain is the only memory layer that spans both cloud and desktop contexts. An employee's personal Aki learns their preferences; Hermes leverages those preferences for department tasks. The combined interaction data trains a custom Qwen model that outperforms generic models on company-specific tasks.

**Target customers**: Mid-market to enterprise (100-10,000 employees). SMB entry via self-serve. Enterprise via sales with VPC/private cloud deployment.

---

## 2. WHAT EXISTS TODAY (Post-Pull Audit)

### ✅ Solid Foundation
| Component | Status | Quality |
|-----------|--------|---------|
| Tenancy / RLS | ✅ Complete | Strong — GUC-based RLS, advisory locks, append-only audit |
| Auth (Clerk JWT + Device JWT) | ✅ Complete | Production-grade — RS256, Ed25519, dev bypass double-gated |
| Audit (hash-chained) | ✅ Complete | Cryptographically verifiable, DB-enforced append-only |
| Brain retrieval (pgvector + BM25 + RRF) | ✅ Complete | Hybrid search with ACL snapshot + live re-check |
| Web UI (Next.js 16) | ✅ Complete | Polished Glyph II design, chat, jobs, connect, audit, devices |
| Aki desktop scaffold (Tauri v2) | ✅ Partial | Tray, shortcut, pairing, sync loop, SQLite journal, MCP stub |
| Per-dept Hermes containers | ✅ Complete | Docker-based, cold-start, hibernate, orphan reaper |
| Composio connectors | ✅ Complete | OAuth, MCP URL generation, 500+ SaaS apps |
| Async jobs (arq + scheduler) | ✅ Complete | Cron, SSE events, cost tracking, Slack delivery |
| Cost tracking | ✅ Complete | Conservative estimates in audit payloads |

### ⚠️ Partial / Gaps
| Component | Gap | Severity |
|-----------|-----|----------|
| Agent runtime registry | In-memory only; no multi-worker support | **Critical** |
| Rate limiting | In-memory slowapi; no per-org limits | **High** |
| Aki chat UI | Stub only; no actual messaging | **High** |
| Aki local Hermes | Spawns process but no crash recovery | **Medium** |
| Brain ↔ Hermes loop | Chat turns not hydrated from Brain retrieval | **High** |
| ACL providers | Notion/Drive stubbed (fail open) | **Medium** |
| RBAC | `_rbac_check()` is no-op | **Medium** |
| Observability | Env vars configured but zero instrumentation | **High** |
| CI/CD / Docker | No API Dockerfile, no docker-compose, no GitHub Actions | **Critical** |
| Billing automation | Rollup computed but not pushed automatically | **Medium** |
| Connection revoke | No delete endpoint | **Low** |
| Chat history | No persistence in web UI | **Medium** |

### ❌ Missing for Enterprise
| Component | What's Missing |
|-----------|---------------|
| Container orchestration | No K8s/Firecracker/gVisor for true isolation |
| Memory consolidation | No temporal KG, no episodic→semantic compression |
| Cross-encoder reranker | No reranking post-RRF |
| OpenTelemetry | No tracing, no metrics, no structured logs |
| API Dockerfile | Can't containerize control plane |
| Load balancer / ingress | No nginx/traefik configs |
| Secrets management | .env only; no Vault/AWS SM |
| Data retention | No TTL/archival policies |
| Multi-org users | Single org per user only |
| Integration tests | No E2E tests against real services |

---

## 3. ARCHITECTURE DECISIONS

### 3.1 Hermes Runtime: Evolution Path

**Current**: Docker containers on local/Railway with in-memory registry.
**Target**: Multi-tier isolation strategy.

```
Tier 1 — SMB / Self-Serve (Today)
  └── Docker containers + in-memory registry
  └── Single API worker process
  └── Shared Postgres/Redis on Neon/Upstash

Tier 2 — Growth / Mid-Market (Phase 3)
  └── Redis-backed container registry + distributed locks
  └── Multiple API workers behind load balancer
  └── Fly.io Machines or Railway per-org containers

Tier 3 — Enterprise (Phase 5)
  └── Firecracker microVMs or Kata Containers per department
  └── Dedicated VPC per customer (logical → physical isolation)
  └── Self-hosted option: customer brings their own cloud
```

**Why this tiering**: Don't over-engineer for Day 1. Docker + in-memory is fine for <100 orgs. Redis registry unlocks horizontal scaling. Firecracker unlocks true multi-tenant security for enterprises that require it.

**Key tool**: [Fly.io Machines](https://fly.io/docs/machines/) — programmatic start/stop, sub-second boots, persistent storage, private networking. Perfect midpoint between Docker and Firecracker.

### 3.2 Brain: Three-Layer Memory Architecture

Current Brain is a solid RAG layer. It needs to evolve into a full **cognitive memory system**:

```
Layer 1 — Episodic (Vector RAG)     [EXISTS — pgvector + BM25 + RRF]
  └── Raw interaction chunks (chat turns, job summaries, journals)
  └── Semantic search for "what happened"
  └── 15-30ms retrieval on <10M rows

Layer 2 — Semantic (Temporal KG)    [NEW — Phase 3]
  └── Extracted facts with validity windows
  └── Entity relationships, preferences, project states
  └── "What was true, when it was true"
  └── Tool: Zep/Graphiti-style temporal KG OR Microsoft GraphRAG

Layer 3 — Procedural (Structured)   [NEW — Phase 4]
  └── Learned skills, few-shot examples, prompt templates
  └── Hermes self-improving skill loop (GEPA)
  └── Exported as LoRA adapters for Qwen fine-tuning
```

**Why three layers**: Research shows (Letta, MemGPT, Zep) that agents need differentiated memory types. Vector RAG for recall, KG for reasoning about state changes, structured for learned behaviors. The combination outperforms any single store by 15-40%.

**Consolidation pipeline**: Nightly job that compresses episodic memories into semantic facts and procedural skills. Prevents linear context growth.

### 3.3 Aki Desktop: Local-First Agent OS

Current Aki is a pairing/sync scaffold. It needs to become a **local agent runtime**:

```
┌─────────────────────────────────────────┐
│  Tauri v2 Frontend (React 19)           │
│  ├── Chat surface (markdown, code)      │
│  ├── Journal viewer                     │
│  ├── Settings / model picker            │
│  └── Voice input (whisper.cpp)          │
├─────────────────────────────────────────┤
│  Rust Backend                           │
│  ├── Local Hermes subprocess            │
│  ├── MCP stdio server manager           │
│  │   ├── aki_mcp_mac (calendar/mail/notes/shell)
│  │   ├── filesystem MCP                 │
│  │   ├── browser MCP (via Playwright)   │
│  │   └── user-installed MCP servers     │
│  ├── SQLite journal                     │
│  ├── Sync loop (→ Brain cloud)          │
│  └── Ed25519 device auth                │
└─────────────────────────────────────────┘
```

**Key decision**: Aki runs its own Hermes instance locally (via `hermes gateway run`), NOT just a thin client to cloud. This enables:
- Offline operation (journal queues, syncs when reconnected)
- Local tool execution (filesystem, shell, browser) without cloud round-trip
- Privacy-sensitive work stays on-device

**MCP Integration**: Support both bundled MCP servers AND user-installed ones from the official MCP registry. Registry API: `registry.modelcontextprotocol.io`. Allow users to one-click install servers like they install VS Code extensions.

### 3.4 Observability: OpenTelemetry-First

**Current state**: Blind. Env vars for PostHog/Sentry/Langfuse exist but zero code instrumentation.

**Target architecture**:
```
Every request → OpenTelemetry tracer
  ├── LLM spans: model, tokens, latency, cost
  ├── Tool spans: name, params, result, success/failure
  ├── Retrieval spans: query, k, latency, sources
  ├── Agent spans: decision points, reasoning traces
  └── Infrastructure spans: DB queries, container lifecycle

Exporters:
  ├── Langfuse (self-hosted) — LLM-specific trace visualization
  ├── Prometheus + Grafana — metrics, dashboards, alerts
  └── Sentry — error tracking
```

**Why OpenTelemetry**: Vendor independence. If Langfuse dies, swap to LangSmith/Phoenix without code changes. Framework-agnostic (works with Hermes, LangGraph, custom code).

**Instrumentation points**:
1. `chat.py`: Full chat completion trace (request → Brain retrieval → Hermes stream → audit)
2. `worker.py`: Job execution trace (enqueue → dispatch → Hermes turn → Brain write → Slack delivery)
3. `brain/retrieval.py`: Retrieval trace (query → vector search → BM25 → RRF → ACL filter)
4. `agent_runtime.py`: Container lifecycle trace (ensure_running → boot → health check → hibernate)
5. `aki-desktop`: Desktop app trace (user input → local Hermes → tool calls → sync)

### 3.5 Billing: Hybrid Model with Cost Containment

**Current**: Cost tracked in audit, manual Stripe push.
**Target**: Automated metering with guardrails.

```
Pricing Model (Hybrid — recommended for B2B AI SaaS):
  ├── Base seat fee: $49/user/month (covers platform + light usage)
  ├── Usage overage: actual cost + 30% margin
  │   └── Tokens, tool calls, compute minutes, storage
  └── Enterprise: Custom contract with committed spend

Cost Containment (Execution Layer):
  ├── Per-org daily spend cap (soft warning → hard stop)
  ├── Per-job max token budget
  ├── Circuit breaker: agent loop terminates after N tool calls
  └── Anomaly detection: flag 10x cost spikes

Metering Pipeline:
  ├── Real-time: Every audit row → streaming aggregation
  ├── Hourly: Rollup to Redis counter per org
  ├── Daily: Persist to billing_usage table + Stripe Meter API
  └── Monthly: Invoice generation
```

**Why hybrid**: Pure usage-based pricing scares finance teams (unpredictable). Per-seat doesn't capture agent value (24/7 operation). Hybrid gives predictability + fairness.

---

## 4. DETAILED COMPONENT PLANS

### 4.1 Hermes ↔ Brain Integration (The Spine)

**Problem**: Brain exists but Hermes doesn't use it. Every chat turn starts with zero context beyond the current session.

**Solution**: Hydrate every Hermes turn with retrieved Brain context.

```
Chat Turn Flow:
  1. User sends message
  2. API embeds query → Brain.retrieve(query, principals, k=5)
  3. Results formatted as system message:
     "Relevant context from your organization's knowledge base:
      [1] Source: PTO Policy (from Notion)
      [2] Source: On-call Runbook (from Confluence)
      ..."
  4. Hermes receives: [system prompt] + [brain context] + [chat history] + [user message]
  5. Hermes responds, possibly using tools
  6. After stream completes:
     a. Full turn (user + assistant) chunked + embedded → Brain (kind=chat_turn)
     b. Tool call results (if any) chunked + embedded → Brain (kind=tool_result)
  7. If job turn: brief + result → Brain (kind=job_summary)
```

**Retrieval trigger**: Not just chat. Also retrieve before:
- Job dispatch (worker gets Brain context about related past jobs)
- Slack delivery (contextualize summary with past channel history)
- Department onboarding (new dept gets org-level memory)

**Context window management**: Brain context is compressed to fit within token budget. Use summarization if retrieved chunks exceed 4k tokens.

### 4.2 Aki Desktop: Full Implementation

**Missing pieces to build**:

#### 4.2.1 Chat Surface UI
- Replace `ChatStub` with full chat interface (mirror web app design)
- Markdown rendering with syntax highlighting (react-markdown + prism)
- Tool event panel (same as web: live tool call tracking)
- Message history persisted in SQLite (not just journal)
- Thread management (new thread, rename, delete)

#### 4.2.2 Local Hermes Integration
- `start_local_hermes()` already spawns process — add:
  - Health check loop (restart if crashed)
  - Model picker UI (Ollama models vs cloud API)
  - Settings: temperature, max_tokens, system prompt
- If Ollama installed, use local model; fallback to cloud API
- CORS proxy pattern: ALL localhost requests route through Rust backend

#### 4.2.3 MCP Server Manager
- Expand `aki_mcp_mac.rs` beyond 4 tools:
  - Calendar: read/write events, list calendars
  - Mail: read unread, send, search
  - Notes: read/write, search
  - Shell: expand whitelist or use deny-list with approval UI
  - Browser: Playwright-based navigation (via separate MCP)
  - Filesystem: read/write files within allow-listed dirs
- MCP server discovery:
  - Read `~/Library/Application Support/Aki/mcp-servers.json`
  - Support installing from MCP registry
  - One-click enable/disable per server

#### 4.2.4 Voice Input (whisper.cpp)
- Hold-to-talk (⌘⇧Space long-press or dedicated key)
- Record audio → WAV → whisper.cpp transcription
- Push-to-talk vs continuous listening modes
- Post-process transcript with lightweight cleanup

#### 4.2.5 Journal & Sync
- Journal viewer UI (timeline of notes)
- Rich text editor for notes
- Auto-tagging (suggest tags based on content)
- Sync queue with retry logic
- Conflict resolution (last-write-wins with notification)

#### 4.2.6 Settings & Onboarding
- Auto-detect existing JWT on launch (fix the empty useEffect)
- Onboarding flow: pair device → choose model → test chat
- Settings: API base URL, model preferences, MCP servers, shortcuts
- Auto-updater (Tauri updater plugin)

### 4.3 Brain Evolution: Temporal Knowledge Graph

**Current**: Vector chunks + BM25 keywords.
**Add**: Temporal facts + memory consolidation.

```
New Tables:
  brain_entities (id, org_id, name, type, canonical_id)
  brain_relationships (id, org_id, subject_id, predicate, object_id, 
                       t_valid_from, t_valid_to, confidence, source_id)
  brain_episodes (id, org_id, summary, start_time, end_time, 
                  participants, location, source_ids)

Consolidation Pipeline (nightly cron):
  1. SELECT chat_turns, job_summaries from last 24h
  2. Extract entities + relationships via LLM (structured output)
  3. Merge with existing KG (update timestamps, resolve conflicts)
  4. Compress old episodes into episode summaries (>30 days)
  5. Export procedural patterns (repeated successful tool sequences)
```

**Tool choice**: Instead of building from scratch, evaluate:
- **Graphiti (Zep)** — temporal KG, bi-temporal facts, open source
- **Mem0** — universal memory layer (vector + graph + KV)
- **Letta (MemGPT)** — tiered OS-inspired memory, highest LongMemEval score
- **Microsoft GraphRAG** — hierarchical community detection

**Recommendation**: Start with Mem0 as the consolidation layer (easiest integration, Apache 2.0). Add Graphiti later for temporal reasoning if needed.

### 4.4 Enterprise Scalability: Multi-Worker + Fly.io

**Current**: Single-process FastAPI with in-memory registry.
**Target**: Horizontally scalable control plane.

```
Redis-Backed Registry:
  ├── Hash: hermes:registry → { "(org_id,dept_id)": {host_port, api_key, started_at, last_touched} }
  ├── Lock: hermes:lock:(org_id):(dept_id) → distributed lock for cold-start
  └── Pub/Sub: hermes:events → broadcast container state changes

Fly.io Machines Integration (alternative to Docker):
  ├── Create machine per (org, dept) on demand
  ├── Machine config: image, env, volume, services
  ├── Start: POST /v1/apps/{app}/machines
  ├── Stop: POST /v1/apps/{app}/machines/{id}/stop
  └── Health: Poll machine internal API
```

**Rate Limiting Upgrade**:
- Replace slowapi in-memory with Redis backend
- Per-org limits: 100 chat requests/min, 50 tool calls/min, 10 job dispatches/min
- Per-user limits within org

### 4.5 Security & Compliance

**Current**: Strong foundation (RLS, audit, hash chain). Missing enterprise features.

```
Additions:
  ├── SOC 2 Type II readiness:
  │   ├── Access logs (who accessed what, when)
  │   ├── Data retention policies (auto-delete after N days)
  │   ├── Encryption at rest (TDE for Postgres)
  │   └── Encryption in transit (TLS 1.3, mTLS for service mesh)
  ├── GDPR compliance:
  │   ├── Right to deletion (cascade delete org + all data)
  │   ├── Data export (JSON dump of all org data)
  │   └── EU data residency (EU Postgres replica)
  ├── RBAC (replace no-op stub):
  │   ├── Roles: super_admin, org_admin, dept_admin, member, viewer
  │   ├── Permissions matrix: 20+ granular permissions
  │   └── Department-scoped connections (dept A can't use dept B's Gmail)
  └── Secrets management:
      ├── Vault integration (HashiCorp or AWS Secrets Manager)
      ├── Credential rotation (auto-rotate Composio tokens)
      └── No secrets in env vars at runtime (fetch from Vault on boot)
```

### 4.6 Training Pipeline: Qwen Fine-Tuning

**Current**: Axolotl + Unsloth configs exist, untested.
**Target**: Automated training pipeline from Brain export.

```
Pipeline:
  1. User triggers export: POST /v1/brain/export?dataset=training
  2. System assembles JSONL from:
     ├── High-quality chat turns (rating ≥ 4)
     ├── Successful job summaries (status=done, cost < threshold)
     ├── Aki journal entries (user-curated highlights)
     └── Tool call trajectories (positive outcomes only)
  3. Data cleaning:
     ├── Deduplication (hash-based)
     ├── PII scrubbing (presidio or regex)
     ├── Quality filtering (rejection sampling)
     └── Balance across domains (HDR — Hard Data Re-sampling)
  4. Format conversion:
     ├── ChatML / Qwen template
     ├── Loss masking (only assistant tokens)
     └── Train/validation split (90/10)
  5. Training:
     ├── Primary: Unsloth + TRL SFTTrainer (fastest, lowest VRAM)
     ├── Fallback: Axolotl (most recipes, YAML-config)
     └── Target: Qwen2.5 7B or 14B LoRA
  6. Evaluation:
     ├── Perplexity on held-out set
     ├── Tool-call accuracy (BFCL benchmark subset)
     ├── Human evaluation (5-point rubric)
     └── A/B test against base model
  7. Deployment:
     ├── Merge LoRA into base model
     ├── Deploy to inference endpoint (vLLM or TGI)
     ├── Gradual rollout (10% → 50% → 100% of traffic)
     └── Fallback to base model on errors
```

**Infrastructure**: Modal.com for training (serverless GPU, scale-to-zero, $3.95/hr H100). RunSpace or RunPod for cheaper alternatives.

---

## 5. OPEN SOURCE TOOLS & VENDORS TO INTEGRATE

### 5.1 Must-Have Integrations

| Category | Tool | Purpose | Integration Point |
|----------|------|---------|-------------------|
| **Agent Runtime** | Hermes Agent 0.13+ (Nous) | Core cloud agent | `services/agent/` Docker image |
| **Local LLM** | Ollama | Local model inference for Aki | Aki desktop bundled or auto-download |
| **MCP Registry** | registry.modelcontextprotocol.io | Discover/install MCP servers | Aki settings UI + web admin |
| **Vector DB** | pgvector (already used) | Embedding storage | Postgres extension |
| **Queue** | arq (already used) | Async job dispatch | Redis-backed worker |
| **Auth** | Clerk (already used) | User auth, org provisioning | JWT templates, webhooks |
| **Connectors** | Composio (already used) | 500+ SaaS OAuth | MCP URL generation |
| **Browser** | Browser Use Cloud | No-API web automation | MCP server |

### 5.2 Strongly Recommended Additions

| Category | Tool | Purpose | Integration Point |
|----------|------|---------|-------------------|
| **Observability** | Langfuse (self-hosted) | LLM trace visualization | OpenTelemetry exporter |
| **Observability** | OpenTelemetry | Vendor-neutral tracing | Instrument all services |
| **Metrics** | Prometheus + Grafana | Infrastructure metrics | Scraping endpoints |
| **Memory** | Mem0 | Universal memory layer (vector+graph+KV) | Brain consolidation pipeline |
| **Container Orchestration** | Fly.io Machines | Per-org isolated compute | Alternative to Docker for prod |
| **Training** | Unsloth | Fast Qwen fine-tuning | `tools/qwen-train/` pipeline |
| **Training** | Modal.com | Serverless GPU training | Cloud training jobs |
| **Durable Execution** | Temporal.io | Long-running workflow orchestration | Worker jobs (Phase 4) |
| **Billing** | Stripe Meter API | Usage-based billing | Daily rollup + invoice |
| **Secrets** | HashiCorp Vault / AWS SM | Runtime secret management | Config loader |
| **CI/CD** | GitHub Actions | Automated testing + deployment | `.github/workflows/` |
| **E2E Testing** | Playwright | Browser automation tests | Web app flows |

### 5.3 Evaluate for Future Phases

| Category | Tool | When to Evaluate |
|----------|------|-----------------|
| **Temporal KG** | Graphiti (Zep) | When agents need historical reasoning |
| **Memory** | Letta (MemGPT) | When context window management becomes critical |
| **GraphRAG** | Microsoft GraphRAG | For whole-corpus analytics |
| **Container Isolation** | Firecracker / Kata | Enterprise tier with untrusted code |
| **Inference Server** | vLLM / TGI | When deploying custom Qwen models |
| **Eval Platform** | Braintrust | Systematic model evaluation |
| **Entitlements** | OpenFGA / SpiceDB | Fine-grained authorization |

---

## 6. IMPLEMENTATION PHASES

### Phase 1: Foundation Hardening (2-3 weeks)
**Goal**: Make what's built production-deployable.

- [ ] API Dockerfile + docker-compose.yml (full stack: API + Postgres + Redis + Hermes)
- [ ] GitHub Actions CI/CD (lint, test, build, deploy)
- [ ] OpenTelemetry instrumentation (chat, worker, brain retrieval, agent runtime)
- [ ] Redis-backed rate limiting (per-org, per-user)
- [ ] Redis-backed Hermes registry (multi-worker safe)
- [ ] API service health checks + graceful shutdown
- [ ] Structured JSON logging (not stdlib text)
- [ ] Web app auth middleware (protect /jobs, /devices, /audit, /admin)
- [ ] Connection revoke/delete endpoint
- [ ] Fix `_pick_free_port()` race condition

### Phase 2: Hermes ↔ Brain Loop (2 weeks)
**Goal**: Make Brain actually useful.

- [ ] Chat pre-retrieval: inject Brain context as system message
- [ ] Chat post-ingestion: persist turns to Brain (kind=chat_turn)
- [ ] Worker pre-retrieval: inject relevant past jobs before dispatch
- [ ] Worker post-ingestion: persist job summaries (kind=job_summary)
- [ ] Tool result ingestion: persist tool outputs (kind=tool_result)
- [ ] Context compression: summarize retrieved chunks if too long
- [ ] Cross-encoder reranker (ms-marco-MiniLM-L-6-v2) post-RRF
- [ ] Brain eval automation: nightly recall@k tests, alert on regression

### Phase 3: Aki Desktop Completion (3-4 weeks)
**Goal**: Ship a usable desktop agent.

- [ ] Full chat UI (markdown, code highlighting, tool events, threads)
- [ ] Local Hermes health monitoring + auto-restart
- [ ] Ollama integration (auto-detect, model download, fallback)
- [ ] MCP server manager UI (install from registry, enable/disable)
- [ ] Expand macOS MCP tools (calendar R/W, mail R/W, notes search, shell expansion)
- [ ] Voice input (whisper.cpp hold-to-talk)
- [ ] Journal viewer + rich text editor
- [ ] Auto-detect paired state on launch
- [ ] Settings panel (model, API URL, shortcuts, MCP)
- [ ] Auto-updater (Tauri updater)
- [ ] Windows/Linux port plan (abstract macOS-specific MCP)

### Phase 4: Enterprise Features (3-4 weeks)
**Goal**: Ready for mid-market sales.

- [ ] RBAC implementation (roles, permissions, dept-scoped connections)
- [ ] Multi-org membership (users in multiple orgs)
- [ ] Admin console (org settings, user management, usage dashboards)
- [ ] Brain memory consolidation (Mem0 integration, nightly pipeline)
- [ ] Temporal.io integration for durable job execution (optional but recommended)
- [ ] Stripe billing automation (metered billing, invoicing, spend caps)
- [ ] Data retention policies (configurable TTL per org)
- [ ] GDPR data export + deletion
- [ ] Fly.io Machines runtime (alternative to Docker)
- [ ] Load balancer config (nginx/traefik)

### Phase 5: Scale & AI Native (4-6 weeks)
**Goal**: Differentiate with custom models.

- [ ] Training data pipeline (automated Brain → JSONL)
- [ ] Unsloth training automation (Modal.com integration)
- [ ] Model evaluation framework (perplexity, tool accuracy, human eval)
- [ ] A/B testing infrastructure (route % traffic to custom model)
- [ ] vLLM inference deployment for custom Qwen
- [ ] Firecracker/Kata evaluation for enterprise isolation
- [ ] Self-hosted deployment option (customer brings cloud)
- [ ] Advanced analytics (usage patterns, cost optimization, ROI dashboards)
- [ ] Partner marketplace (pre-built department templates)

---

## 7. TECHNOLOGY CHOICES & JUSTIFICATIONS

### Why Tauri over Electron for Aki
- **Binary size**: 3MB vs 120MB — critical for auto-updater bandwidth
- **Memory**: 20MB vs 250MB — users won't kill it for resource usage
- **Security**: Rust backend with explicit allowlist, no Node.js attack surface
- **Native performance**: Direct system integration (keychain, global shortcuts)
- **Future-proof**: Tauri v2 supports mobile (iOS/Android) from same codebase

### Why Postgres + pgvector over Pinecone/Weaviate
- **Operational simplicity**: One database, not two
- **ACID + RLS**: Transactional consistency with tenant isolation built-in
- **Hybrid search**: tsvector BM25 + pgvector cosine in single query
- **Cost**: No per-vector pricing; scales with Postgres instance
- **Enterprise**: Self-hostable, no vendor lock-in
- **Limit**: 10-50M vectors per instance; beyond that shard or consider dedicated VDB

### Why arq over Celery/RQ
- **Async-native**: Built on asyncio, matches FastAPI's paradigm
- **Type-safe**: Pydantic models for jobs
- **Simple**: Redis only, no broker complexity
- **Limit**: For enterprise durability, evaluate Temporal.io (crash-proof, replayable)

### Why Unsloth over Axolotl for Training
- **Speed**: 1.5× faster training, 50% less VRAM
- **Simplicity**: Python-native, no YAML config overhead
- **Iterate faster**: Tighter feedback loop for experimentation
- **Axolotl role**: Recipe library for exotic architectures; fallback when Unsloth doesn't support

### Why Composio + MCP over native integrations
- **500+ apps**: Instant breadth without building OAuth for each
- **MCP standard**: Decouples tool definitions from agent runtime
- **Future-proof**: New SaaS apps appear in Composio automatically
- **Enterprise path**: Can swap to Nango/self-hosted without schema changes

---

## 8. RISK MITIGATION

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Hermes 0.13 has breaking changes in next release | High | High | Pin version, maintain compatibility shim, evaluate LangGraph as fallback runtime |
| pgvector performance degrades at >10M vectors | Medium | High | Monitor vector count, plan shard strategy, evaluate Qdrant/Weaviate as overflow |
| Composio API changes or rate limits | Medium | Medium | Abstract connector layer (already done), cache MCP URLs, build fallback native OAuth |
| Desktop app rejected from app stores | Low | Medium | Distribute via direct download + auto-updater; app stores are Phase 5 |
| Custom Qwen model underperforms base | Medium | High | A/B testing, automatic fallback, human-in-the-loop evaluation gating |
| Multi-worker registry bugs | Medium | High | Extensive integration tests, Redis transactions, graceful degradation to single-worker |
| Security vulnerability in agent sandbox | Low | High | Defense in depth: RLS + ACL + audit; evaluate gVisor/Firecracker for untrusted code |
| Customer requires on-premise deployment | Medium | High | Design for self-host from start (Docker Compose, no managed-only dependencies) |

---

## 9. SUCCESS METRICS

### Technical Metrics
- **Cold start time**: <15s for Hermes container (currently ~10s)
- **Chat latency**: P95 <3s to first token (currently ~2s)
- **Brain retrieval**: P95 <50ms for hybrid search (currently ~20ms)
- **Aki sync**: <5s from local journal to cloud Brain
- **Uptime**: 99.9% for API, 99.5% for worker
- **Test coverage**: 80%+ unit, 50%+ integration

### Business Metrics
- **Time to value**: New org productive in <10 minutes
- **Agent task completion**: >85% of briefs complete without human intervention
- **Brain relevance**: Recall@5 >80% on eval set
- **Cost per task**: Decreasing 20% month-over-month via optimization
- **NPS**: >50 from beta users

---

## 10. IMMEDIATE NEXT STEPS (This Week)

1. **Set up CI/CD**: GitHub Actions workflow for lint + test + build
2. **Dockerize API**: Create `services/api/Dockerfile` and root `docker-compose.yml`
3. **Instrument with OpenTelemetry**: Add tracing to chat endpoint as pilot
4. **Fix web auth gaps**: Add Clerk middleware protection to all routes
5. **Brain loop PoC**: Inject Brain retrieval into chat flow, measure latency impact
6. **Aki chat UI**: Replace stub with functional chat surface

---

*This plan is designed to be executed in order, with each phase building on the previous. The goal is not perfection on Day 1, but a clear path from "solid prototype" to "enterprise-grade platform" over 12-16 weeks.*
