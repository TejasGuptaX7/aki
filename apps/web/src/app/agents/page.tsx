"use client";

import * as React from "react";
import Link from "next/link";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { agentsApi, ApiError } from "@/lib/api";

export default function AgentsPage() {
  const { agents, status, error, refresh } = useAgents();
  const tok = useAuthToken();
  const [creating, setCreating] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [pageErr, setPageErr] = React.useState<string | null>(null);

  async function create() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true); setPageErr(null);
    try {
      await agentsApi.create(tok, { name });
      await refresh();
      setNewName("");
      setCreating(false);
    } catch (e) {
      setPageErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true); setPageErr(null);
    try {
      await agentsApi.remove(tok, id);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setPageErr("Can't archive — this is your only active agent. Create another first.");
      } else {
        setPageErr(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  const active = agents.filter((a) => a.status === "active");
  const hibernated = agents.filter((a) => a.status === "hibernated");
  const archived = agents.filter((a) => a.status === "archived");
  const shownError = pageErr ?? error;

  return (
    <AppShell>
      <SectionHeader
        kicker="/00 · agents"
        title={<>One brief becomes <em style={{ fontStyle: "italic", fontWeight: 500 }}>one tireless coworker.</em></>}
        lede="Each agent is its own profile — its own memory, its own connections. Spin up as many as your team needs."
        right={
          <button onClick={() => setCreating(true)} style={primaryBtn}>
            + New agent
          </button>
        }
      />

      {shownError && <ErrorBanner>{shownError}</ErrorBanner>}

      {creating && (
        <div style={{ padding: "24px 56px", borderBottom: `1px solid ${theme.hair}`, background: theme.bgSoft }}>
          <Label>Name your agent</Label>
          <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") setCreating(false); }}
              placeholder="Aki Sales"
              style={inputStyle}
            />
            <button onClick={create} disabled={busy || !newName.trim()} style={primaryBtn}>
              {busy ? "…" : "Create"}
            </button>
            <button onClick={() => { setCreating(false); setNewName(""); }} style={secondaryBtn}>
              Cancel
            </button>
          </div>
          <div style={{
            marginTop: 8, fontFamily: theme.mono, fontSize: 10,
            color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase",
          }}>
            you can edit the brief after creation · or use /onboarding for a guided setup
          </div>
        </div>
      )}

      <section style={{ padding: "32px 56px 64px" }}>
        {status === "loading" ? (
          <SkeletonList/>
        ) : agents.length === 0 ? (
          <Empty>No agents yet. <Link href="/onboarding" style={{ color: theme.accent, textDecoration: "none" }}>Start with onboarding →</Link></Empty>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            <Group label={`active · ${active.length}`}>
              {active.map((a) => <AgentRow key={a.id} agent={a} onDelete={() => remove(a.id)} canDelete={active.length > 1}/>)}
            </Group>
            {hibernated.length > 0 && (
              <Group label={`hibernated · ${hibernated.length}`}>
                {hibernated.map((a) => <AgentRow key={a.id} agent={a} onDelete={() => remove(a.id)} canDelete/>)}
              </Group>
            )}
            {archived.length > 0 && (
              <Group label={`archived · ${archived.length}`}>
                {archived.map((a) => <AgentRow key={a.id} agent={a}/>)}
              </Group>
            )}
          </div>
        )}
      </section>
    </AppShell>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em",
        textTransform: "uppercase", color: theme.inkFaint, marginBottom: 14,
      }}>{label}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {children}
      </div>
    </div>
  );
}

function AgentRow({ agent, onDelete, canDelete }: {
  agent: import("@/lib/api").Agent;
  onDelete?: () => void;
  canDelete?: boolean;
}) {
  const lastActive = agent.hibernated_at
    ? `hibernated ${new Date(agent.hibernated_at).toLocaleDateString()}`
    : `created ${new Date(agent.created_at).toLocaleDateString()}`;
  return (
    <div style={{
      padding: "18px 22px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      display: "grid", gridTemplateColumns: "1fr auto auto", gap: 18, alignItems: "center",
    }}>
      <div style={{ minWidth: 0 }}>
        <Link href={`/agents/${agent.id}`} style={{
          fontFamily: theme.display, fontWeight: 600, fontSize: 22,
          letterSpacing: "-0.015em", color: theme.ink, textDecoration: "none",
        }}>{agent.name}</Link>
        <div style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.12em", marginTop: 4,
        }}>
          {agent.slug} · {lastActive}
        </div>
      </div>
      <Link href={`/chat/${agent.id}`} style={{
        fontFamily: theme.body, fontSize: 13, fontWeight: 500,
        color: theme.inkDim, textDecoration: "none",
        padding: "8px 16px", border: `1px solid ${theme.hair}`,
        borderRadius: 999,
      }}>Chat</Link>
      {onDelete && canDelete && agent.status === "active" && (
        <button onClick={onDelete} style={dangerBtn}>Archive</button>
      )}
      {onDelete && !canDelete && agent.status === "active" && (
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>last active</span>
      )}
    </div>
  );
}

function SkeletonList() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{
          padding: "18px 22px", background: theme.bgSoft,
          border: `1px solid ${theme.hair}`, height: 64,
        }}>
          <div style={{ height: 22, width: "30%", background: "rgba(241,237,224,0.06)", marginBottom: 8 }}/>
          <div style={{ height: 11, width: "20%", background: "rgba(241,237,224,0.04)" }}/>
        </div>
      ))}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "28px 30px", background: theme.bgSoft,
      border: `1px dashed ${theme.hair}`,
      fontFamily: theme.display, fontStyle: "italic", fontWeight: 500,
      fontSize: 18, color: theme.inkDim, letterSpacing: "-0.01em",
    }}>{children}</div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.22em", textTransform: "uppercase",
    }}>{children}</div>
  );
}

const inputStyle: React.CSSProperties = {
  flex: 1, background: theme.bg, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "10px 14px", fontFamily: theme.body, fontSize: 15,
  outline: "none",
};

const primaryBtn: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 13,
  padding: "10px 22px", borderRadius: 999, cursor: "pointer",
};

const secondaryBtn: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "10px 18px", borderRadius: 999, cursor: "pointer",
};

const dangerBtn: React.CSSProperties = {
  background: "transparent", color: "#ee5959",
  border: "1px solid rgba(238,89,89,0.32)",
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "8px 16px", borderRadius: 999, cursor: "pointer",
};
