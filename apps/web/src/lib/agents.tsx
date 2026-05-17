"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { Agent, agentsApi } from "./api";

type Status = "loading" | "ready" | "error";

type AgentsCtx = {
  agents: Agent[];
  status: Status;
  error: string | null;
  refresh: () => Promise<void>;
};

const Ctx = React.createContext<AgentsCtx | null>(null);

export function AgentsProvider({ children }: { children: React.ReactNode }) {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [agents, setAgents] = React.useState<Agent[]>([]);
  const [status, setStatus] = React.useState<Status>("loading");
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    if (!isSignedIn) {
      setAgents([]);
      setStatus("ready");
      return;
    }
    setError(null);
    try {
      const list = await agentsApi.list(() => getToken({ template: "aki" }));
      setAgents(list);
      setStatus("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  }, [getToken, isSignedIn]);

  React.useEffect(() => {
    if (!isLoaded) return;
    refresh();
  }, [isLoaded, refresh]);

  const value = React.useMemo(
    () => ({ agents, status, error, refresh }),
    [agents, status, error, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAgents(): AgentsCtx {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useAgents called outside <AgentsProvider>");
  return v;
}

/**
 * Pick the "default" agent — used when the user hits a route that needs
 * an agent context but didn't specify one (e.g. /chat redirects here).
 * Prefer the last-used agent from localStorage; otherwise first active.
 */
export function pickDefaultAgent(agents: Agent[]): Agent | null {
  if (!agents.length) return null;
  const active = agents.filter((a) => a.status === "active");
  const pool = active.length ? active : agents;
  if (typeof window !== "undefined") {
    const last = window.localStorage.getItem("aki.lastAgentId");
    if (last) {
      const hit = pool.find((a) => a.id === last);
      if (hit) return hit;
    }
  }
  return pool[0];
}

export function rememberAgent(id: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem("aki.lastAgentId", id);
}

export function useAuthToken() {
  const { getToken } = useAuth();
  return React.useCallback(() => getToken({ template: "aki" }), [getToken]);
}
