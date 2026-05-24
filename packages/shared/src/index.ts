/**
 * Shared types and contracts for the Aki platform.
 *
 * Used by:
 *   - apps/web      (Next.js frontend)
 *   - apps/aki-desktop (Tauri desktop app)
 *   - services/api  (FastAPI backend — manually kept in sync)
 */

// ── Chat ───────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  name?: string;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
}

export interface ToolEvent {
  kind: string;
  name: string;
  input?: Record<string, unknown>;
  output?: string;
  error?: string;
  duration_ms?: number;
}

export type ChatStage =
  | "idle"
  | "connecting"
  | "waking"
  | "thinking"
  | "tools-active"
  | "streaming"
  | "error";

// ── Jobs ───────────────────────────────────────────────────────────────────

export interface Job {
  id: string;
  brief: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  schedule_cron: string | null;
  next_run_at: string | null;
  deadline_at: string | null;
  result_summary: string | null;
  cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface JobEvent {
  ts: string;
  kind: string;
  payload: Record<string, unknown>;
}

// ── Connections ────────────────────────────────────────────────────────────

export interface Connection {
  id: string;
  provider: string;
  status: "pending" | "active" | "disabled" | "error";
  scopes: string[];
  external_account_id: string | null;
  created_at: string;
}

// ── Devices ────────────────────────────────────────────────────────────────

export interface AkiDevice {
  id: string;
  name: string;
  pubkey: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

// ── Audit ──────────────────────────────────────────────────────────────────

export interface AuditRow {
  id: number;
  actor: string;
  action: string;
  target: string | null;
  payload: Record<string, unknown>;
  content_hash: string;
  prev_hash: string | null;
  created_at: string;
}

// ── Admin ──────────────────────────────────────────────────────────────────

export interface OrgSettings {
  id: string;
  name: string;
  created_at: string;
  hermes_model_name: string | null;
  hermes_idle_minutes: number;
  spend_cap_hard: number | null;
  spend_cap_soft: number | null;
  data_retention_days: number | null;
}

export interface OrgUser {
  id: string;
  clerk_user_id: string;
  email: string | null;
  created_at: string;
  role: string;
}

export interface UsageDay {
  day: string;
  cost_usd: number;
  tool_calls: number;
  chats: number;
  jobs: number;
}

export interface UsageDashboard {
  total_cost_30d: number;
  total_chats_30d: number;
  total_jobs_30d: number;
  total_tool_calls_30d: number;
  daily: UsageDay[];
  top_departments: Array<{
    dept_id: string;
    events: number;
    cost: number;
  }>;
}

// ── Brain ──────────────────────────────────────────────────────────────────

export interface BrainSource {
  id: string;
  scope: "org" | "department" | "user";
  scope_id: string | null;
  kind: string;
  origin: string;
  uri: string | null;
  title: string | null;
  acl_principals: string[];
  created_at: string;
}

export interface BrainChunk {
  id: string;
  source_id: string;
  chunk_index: number;
  content: string;
  token_count: number;
  created_at: string;
}

export interface RetrieveRequest {
  query: string;
  principals: string[];
  k?: number;
}

export interface RetrieveHit {
  chunk: BrainChunk;
  source: BrainSource;
  score: number;
}

// ── SSE ────────────────────────────────────────────────────────────────────

export interface SseChunk {
  data: string;
}
