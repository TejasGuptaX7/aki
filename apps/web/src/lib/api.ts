import { API_URL } from "./theme";

export type Agent = {
  id: string;
  name: string;
  slug: string;
  status: "active" | "hibernated" | "archived";
  created_at: string;
  hibernated_at: string | null;
};

export type AgentDetail = Agent & {
  system_prompt: string;
  browser_profile_id: string | null;
  updated_at: string;
};

export type Connection = {
  id: string;
  provider: string;
  status: string;
  scopes: string[];
  external_account_id: string | null;
  agent_id: string | null;
  created_at: string;
};

export type AuditRow = {
  id: number;
  actor: string;
  action: string;
  target: string | null;
  payload: Record<string, unknown>;
  content_hash: string;
  prev_hash: string | null;
  agent_id: string | null;
  created_at: string;
};

export type AuditPage = {
  items: AuditRow[];
  next_before_id: number | null;
};

export type Approval = {
  id: string;
  agent_id: string;
  kind: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type Fetcher = () => Promise<string | null>;

async function request<T>(
  getToken: Fetcher,
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new ApiError(r.status, text, `${method} ${path} ${r.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// Agents -------------------------------------------------------------

export type AgentTemplate = {
  key: string;
  name: string;
  blurb: string;
  suggested_tools: string[];
};

export type ChatMessage = {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

export const agentsApi = {
  list: (gt: Fetcher) => request<Agent[]>(gt, "GET", "/agents"),
  get: (gt: Fetcher, id: string) => request<AgentDetail>(gt, "GET", `/agents/${id}`),
  create: (gt: Fetcher, body: { name: string; system_prompt?: string }) =>
    request<AgentDetail>(gt, "POST", "/agents", body),
  update: (gt: Fetcher, id: string, body: { name?: string; system_prompt?: string }) =>
    request<AgentDetail>(gt, "PATCH", `/agents/${id}`, body),
  remove: (gt: Fetcher, id: string) => request<void>(gt, "DELETE", `/agents/${id}`),
  listTemplates: (gt: Fetcher) => request<AgentTemplate[]>(gt, "GET", "/agents/templates"),
  createFromTemplate: (gt: Fetcher, key: string, body?: { name?: string }) =>
    request<AgentDetail>(gt, "POST", `/agents/from-template/${encodeURIComponent(key)}`, body ?? {}),
  listMessages: (gt: Fetcher, id: string, opts?: { limit?: number; before_id?: number }) => {
    const params = new URLSearchParams();
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.before_id) params.set("before_id", String(opts.before_id));
    const qs = params.toString();
    return request<ChatMessage[]>(gt, "GET", `/agents/${id}/messages${qs ? `?${qs}` : ""}`);
  },
};

// Connections --------------------------------------------------------

export type OAuthStartResponse = {
  auth_url: string;
  state: string;
  provider: string;
  agent_id: string | null;
};

export type ArcadeStartResponse = {
  auth_id: string;
  auth_url: string;
  status: string;
  user_id: string;
  agent_id: string | null;
};

export type ArcadeStatusResponse = {
  id?: string;
  status: "not_started" | "pending" | "completed" | "failed" | string;
  url?: string;
  provider_id?: string;
  user_id?: string;
  scopes?: string[];
  context?: Record<string, unknown>;
};

export const connectionsApi = {
  list: (gt: Fetcher, agentId?: string) => {
    const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return request<Connection[]>(gt, "GET", `/connections${q}`);
  },
  oauthStart: (gt: Fetcher, provider: string, agentId?: string) => {
    const params = new URLSearchParams({ provider });
    if (agentId) params.set("agent_id", agentId);
    return request<OAuthStartResponse>(
      gt, "POST", `/connections/oauth/start?${params.toString()}`,
    );
  },
  oauthCallback: (gt: Fetcher, body: { code: string; state: string }) =>
    request<Connection>(gt, "POST", `/connections/oauth/callback`, body),
  browserEnable: (gt: Fetcher, agentId?: string) => {
    const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return request<unknown>(gt, "POST", `/connections/browser/enable${q}`);
  },
  browserDisable: (gt: Fetcher, agentId?: string) => {
    const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return request<unknown>(gt, "POST", `/connections/browser/disable${q}`);
  },
  arcadeStart: (
    gt: Fetcher,
    body: { provider: string; agent_id?: string | null; scopes?: string[] },
  ) => request<ArcadeStartResponse>(gt, "POST", `/connections/arcade/start`, body),
  arcadeStatus: (gt: Fetcher, authId: string, wait = 0) => {
    const params = new URLSearchParams({ auth_id: authId });
    if (wait > 0) params.set("wait", String(wait));
    return request<ArcadeStatusResponse>(
      gt, "GET", `/connections/arcade/status?${params.toString()}`,
    );
  },
  arcadeRecord: (
    gt: Fetcher,
    body: { auth_id: string; agent_id?: string | null },
  ) => request<Connection>(gt, "POST", `/connections/arcade/record`, body),
};

// Audit --------------------------------------------------------------

export const auditApi = {
  list: (gt: Fetcher, opts?: { agentId?: string; limit?: number; before_id?: number }) => {
    const params = new URLSearchParams();
    if (opts?.agentId) params.set("agent_id", opts.agentId);
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.before_id) params.set("before_id", String(opts.before_id));
    const qs = params.toString();
    return request<AuditPage>(gt, "GET", `/audit${qs ? `?${qs}` : ""}`);
  },
};

// Approvals --------------------------------------------------------

export const approvalsApi = {
  list: async (gt: Fetcher): Promise<Approval[]> => {
    try {
      return await request<Approval[]>(gt, "GET", "/approvals");
    } catch (e) {
      // The list endpoint may briefly 404 during a backend deploy; treat
      // that as an empty inbox so the UI renders its empty state cleanly
      // instead of showing a scary error.
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return [];
      throw e;
    }
  },
  approve: (gt: Fetcher, id: string, note?: string) =>
    request<unknown>(gt, "POST", `/approvals/${encodeURIComponent(id)}/approve`,
      note ? { note } : undefined),
  deny: (gt: Fetcher, id: string, note?: string) =>
    request<unknown>(gt, "POST", `/approvals/${encodeURIComponent(id)}/deny`,
      note ? { note } : undefined),
};
