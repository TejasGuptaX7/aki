"use client";

import * as React from "react";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { auditApi, AuditRow } from "@/lib/api";

const ALL = "__all__";

export default function AuditPage() {
  const tok = useAuthToken();
  const { agents } = useAgents();
  const [agentFilter, setAgentFilter] = React.useState<string>(ALL);
  const [rows, setRows] = React.useState<AuditRow[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [openId, setOpenId] = React.useState<number | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setRows(null); setErr(null);
    (async () => {
      try {
        const page = await auditApi.list(tok, {
          limit: 100,
          agentId: agentFilter === ALL ? undefined : agentFilter,
        });
        if (!cancelled) setRows(page.items);
      } catch (e: unknown) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [tok, agentFilter]);

  const agentNameById = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const a of agents) m.set(a.id, a.name);
    return m;
  }, [agents]);

  const stats = React.useMemo(() => {
    if (!rows) return null;
    const completes = rows.filter((r) => r.action === "chat.complete");
    const toolCalls = rows.filter((r) => r.action === "chat.tool_call").length;
    const cost = completes.reduce((s, r) => s + Number((r.payload as { cost_usd?: number }).cost_usd ?? 0), 0);
    return { total: rows.length, chats: completes.length, toolCalls, cost };
  }, [rows]);

  return (
    <AppShell>
      <SectionHeader
        kicker="/03 · audit"
        title={<>Every action is <em style={{ fontStyle: "italic", fontWeight: 500 }}>a small essay.</em></>}
        lede="Hash-chained from row one. Append-only at the database level. Filter by agent to see one coworker's trail in isolation."
        right={
          <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} style={selectStyle}>
            <option value={ALL}>All agents</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        }
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      {stats && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0,
          padding: "0 56px", marginTop: 24,
        }}>
          <StatCard label="events" value={stats.total.toString()}/>
          <StatCard label="chats" value={stats.chats.toString()}/>
          <StatCard label="tool calls" value={stats.toolCalls.toString()}/>
          <StatCard label="cost (usd)" value={`$${stats.cost.toFixed(4)}`}/>
        </div>
      )}

      <section style={{ padding: "32px 56px 64px" }}>
        {rows === null ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {[0,1,2,3,4,5].map((i) => <SkeletonRow key={i}/>)}
          </div>
        ) : rows.length === 0 ? (
          <div style={{
            padding: "28px 30px", background: theme.bgSoft,
            border: `1px dashed ${theme.hair}`,
            fontFamily: theme.display, fontStyle: "italic", fontSize: 18, color: theme.inkDim,
          }}>
            {agentFilter === ALL
              ? "No activity yet. Send Aki a message to see the trail appear here."
              : "No activity for this agent yet."}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <HeaderRow/>
            {rows.map((r) => (
              <EventRow key={r.id} row={r}
                agentLabel={r.agent_id ? agentNameById.get(r.agent_id) ?? short(r.agent_id) : null}
                open={openId === r.id}
                onToggle={() => setOpenId(openId === r.id ? null : r.id)}/>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: "18px 22px",
      borderRight: `1px solid ${theme.hair}`,
      borderTop: `1px solid ${theme.hair}`,
      borderBottom: `1px solid ${theme.hair}`,
    }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
        letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 8,
      }}>{label}</div>
      <div style={{
        fontFamily: theme.display, fontSize: 32, fontWeight: 600, letterSpacing: "-0.02em",
      }}>{value}</div>
    </div>
  );
}

function HeaderRow() {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "70px 140px 130px 1fr 200px 110px",
      gap: 16, padding: "10px 16px", background: theme.bgSoft,
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.18em", textTransform: "uppercase",
    }}>
      <span>id</span><span>action</span><span>agent</span><span>target / preview</span><span>time</span><span style={{ textAlign: "right" }}>cost</span>
    </div>
  );
}

function EventRow({ row, agentLabel, open, onToggle }: {
  row: AuditRow; agentLabel: string | null; open: boolean; onToggle: () => void;
}) {
  const cost = (row.payload as { cost_usd?: number }).cost_usd;
  const preview = previewFor(row);
  return (
    <>
      <button onClick={onToggle} style={{
        display: "grid", gridTemplateColumns: "70px 140px 130px 1fr 200px 110px",
        gap: 16, padding: "12px 16px",
        background: open ? "rgba(241,237,224,0.04)" : "transparent",
        border: "none", borderTop: `1px solid ${theme.hair}`,
        color: theme.ink, fontFamily: theme.body, fontSize: 13,
        textAlign: "left", cursor: "pointer", width: "100%",
      }}>
        <span style={{ fontFamily: theme.mono, color: theme.inkFaint }}>{row.id}</span>
        <span style={{ fontFamily: theme.mono, color: colorFor(row.action) }}>{row.action}</span>
        <span style={{
          fontFamily: theme.mono, fontSize: 12,
          color: agentLabel ? theme.inkLede : theme.inkFaint,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{agentLabel ?? "—"}</span>
        <span style={{
          color: theme.inkLede,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{preview}</span>
        <span style={{ fontFamily: theme.mono, color: theme.inkDim, fontSize: 11 }}>
          {new Date(row.created_at).toLocaleString()}
        </span>
        <span style={{
          fontFamily: theme.mono, color: cost ? theme.accent : theme.inkFaint,
          textAlign: "right",
        }}>
          {cost !== undefined ? `$${cost.toFixed(4)}` : ""}
        </span>
      </button>
      {open && (
        <div style={{
          padding: "16px 16px 20px",
          background: "rgba(241,237,224,0.03)",
          borderTop: `1px solid ${theme.hair}`,
        }}>
          <KVRow k="content_hash" v={row.content_hash}/>
          <KVRow k="prev_hash" v={row.prev_hash || "(root)"}/>
          {row.target && <KVRow k="target" v={row.target}/>}
          <KVRow k="actor" v={row.actor}/>
          {row.agent_id && <KVRow k="agent_id" v={row.agent_id}/>}
          <div style={{
            marginTop: 14, fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
            letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 8,
          }}>payload</div>
          <pre style={{
            fontFamily: theme.mono, fontSize: 12, color: theme.inkLede,
            background: theme.bgSoft, border: `1px solid ${theme.hair}`,
            padding: "12px 14px", margin: 0, borderRadius: 4,
            overflowX: "auto", whiteSpace: "pre-wrap",
          }}>
            {JSON.stringify(row.payload, null, 2)}
          </pre>
        </div>
      )}
    </>
  );
}

function KVRow({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 16, marginBottom: 6 }}>
      <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.14em" }}>{k}</span>
      <span style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkLede, wordBreak: "break-all" }}>{v}</span>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "70px 140px 130px 1fr 200px 110px",
      gap: 16, padding: "12px 16px", borderTop: `1px solid ${theme.hair}`,
    }}>
      {[0,1,2,3,4,5].map((i) => (
        <div key={i} style={{ height: 14, background: "rgba(241,237,224,0.04)" }}/>
      ))}
    </div>
  );
}

function previewFor(row: AuditRow): string {
  const p = row.payload as Record<string, unknown>;
  if (row.action === "chat.tool_call") {
    return (p.label as string) || `${p.tool} · ${p.status}`;
  }
  if (row.action === "chat.complete") {
    const u = (p.usage as { total_tokens?: number } | undefined) ?? {};
    return `${p.model} · ${u.total_tokens ?? 0} tok · ${p.duration_ms}ms · ${p.tool_calls} tools`;
  }
  if (row.action === "chat.start") {
    return `${p.bytes ?? "?"} bytes`;
  }
  return JSON.stringify(p).slice(0, 80);
}

function colorFor(action: string): string {
  if (action.endsWith(".start")) return theme.inkDim;
  if (action.endsWith(".complete")) return theme.accent;
  if (action.includes(".tool_call")) return "#e3dcc5";
  return theme.ink;
}

function short(id: string): string {
  return id.slice(0, 8);
}

const selectStyle: React.CSSProperties = {
  background: theme.bg, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 999,
  padding: "8px 16px", fontFamily: theme.body, fontSize: 13,
  outline: "none", cursor: "pointer",
};
