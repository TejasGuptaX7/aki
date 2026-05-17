"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";

type Row = {
  id: number;
  actor: string;
  action: string;
  target: string | null;
  payload: Record<string, unknown>;
  content_hash: string;
  prev_hash: string | null;
  created_at: string;
};

export default function AuditPage() {
  const { getToken } = useAuth();
  const [rows, setRows] = React.useState<Row[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [openId, setOpenId] = React.useState<number | null>(null);

  React.useEffect(() => {
    (async () => {
      try {
        const token = await getToken({ template: "aki" });
        const r = await fetch(`${API_URL}/audit?limit=100`, { headers: { Authorization: `Bearer ${token}` } });
        if (!r.ok) throw new Error(`GET /audit ${r.status}`);
        const d = await r.json();
        setRows(d.items);
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [getToken]);

  // Roll-up stats for the header
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
        lede="Hash-chained from row one. Append-only at the database level. Verify the chain locally with the hash + prev_hash fields."
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0, padding: "0 56px", marginTop: 24 }}>
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
          <div style={{ padding: "28px 30px", background: theme.bgSoft, border: `1px dashed ${theme.hair}`, fontFamily: theme.display, fontStyle: "italic", fontSize: 18, color: theme.inkDim }}>
            No activity yet. Send Aki a message to see the trail appear here.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <HeaderRow/>
            {rows.map((r) => (
              <EventRow key={r.id} row={r} open={openId === r.id} onToggle={() => setOpenId(openId === r.id ? null : r.id)}/>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: "18px 22px", borderRight: `1px solid ${theme.hair}`, borderTop: `1px solid ${theme.hair}`, borderBottom: `1px solid ${theme.hair}` }}>
      <div style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
      <div style={{ fontFamily: theme.display, fontSize: 32, fontWeight: 600, letterSpacing: "-0.02em" }}>{value}</div>
    </div>
  );
}

function HeaderRow() {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "70px 140px 1fr 200px 110px",
      gap: 16, padding: "10px 16px", background: theme.bgSoft,
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase",
    }}>
      <span>id</span><span>action</span><span>target / preview</span><span>time</span><span style={{ textAlign: "right" }}>cost</span>
    </div>
  );
}

function EventRow({ row, open, onToggle }: { row: Row; open: boolean; onToggle: () => void }) {
  const cost = (row.payload as { cost_usd?: number }).cost_usd;
  const preview = previewFor(row);
  return (
    <>
      <button onClick={onToggle} style={{
        display: "grid", gridTemplateColumns: "70px 140px 1fr 200px 110px",
        gap: 16, padding: "12px 16px",
        background: open ? "rgba(241,237,224,0.04)" : "transparent",
        border: "none", borderTop: `1px solid ${theme.hair}`,
        color: theme.ink, fontFamily: theme.body, fontSize: 13,
        textAlign: "left", cursor: "pointer", width: "100%",
      }}>
        <span style={{ fontFamily: theme.mono, color: theme.inkFaint }}>{row.id}</span>
        <span style={{ fontFamily: theme.mono, color: colorFor(row.action) }}>{row.action}</span>
        <span style={{ color: theme.inkLede, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{preview}</span>
        <span style={{ fontFamily: theme.mono, color: theme.inkDim, fontSize: 11 }}>{new Date(row.created_at).toLocaleString()}</span>
        <span style={{ fontFamily: theme.mono, color: cost ? theme.accent : theme.inkFaint, textAlign: "right" }}>
          {cost !== undefined ? `$${cost.toFixed(4)}` : ""}
        </span>
      </button>
      {open && (
        <div style={{ padding: "16px 16px 20px", background: "rgba(241,237,224,0.03)", borderTop: `1px solid ${theme.hair}` }}>
          <KVRow k="content_hash" v={row.content_hash}/>
          <KVRow k="prev_hash" v={row.prev_hash || "(root)"}/>
          {row.target && <KVRow k="target" v={row.target}/>}
          <KVRow k="actor" v={row.actor}/>
          <div style={{ marginTop: 14, fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 8 }}>
            payload
          </div>
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
    <div style={{ display: "grid", gridTemplateColumns: "70px 140px 1fr 200px 110px", gap: 16, padding: "12px 16px", borderTop: `1px solid ${theme.hair}` }}>
      {[0,1,2,3,4].map((i) => (
        <div key={i} style={{ height: 14, background: "rgba(241,237,224,0.04)" }}/>
      ))}
    </div>
  );
}

function previewFor(row: Row): string {
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
