"use client";

import * as React from "react";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { approvalsApi, Approval } from "@/lib/api";

/**
 * Approvals inbox. The backend endpoint (GET /approvals) lands in a
 * follow-up; the API client returns [] for 404/405 so the page renders
 * its empty state cleanly today. When the endpoint exists, this page
 * already polls it every 10s and re-renders.
 */
export default function ApprovalsPage() {
  const tok = useAuthToken();
  const { agents } = useAgents();
  const [items, setItems] = React.useState<Approval[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => {
    let mounted = true;
    const tick = async () => {
      try {
        const list = await approvalsApi.list(tok);
        if (mounted) { setItems(list); setErr(null); }
      } catch (e) {
        if (mounted) setErr(e instanceof Error ? e.message : String(e));
      }
    };
    tick();
    const id = setInterval(tick, 10_000);
    return () => { mounted = false; clearInterval(id); };
  }, [tok]);

  const agentName = React.useCallback(
    (id: string) => agents.find((a) => a.id === id)?.name ?? id.slice(0, 8),
    [agents],
  );

  return (
    <AppShell>
      <SectionHeader
        kicker="/04 · approvals"
        title={<>What the agent <em style={{ fontStyle: "italic", fontWeight: 500 }}>wants your nod on.</em></>}
        lede="Outbound emails, high-value moves, anything the agent flagged as needing a human first. Approve or reject; the trail lands in audit either way."
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      <section style={{ padding: "32px 56px 64px" }}>
        {items === null ? (
          <div style={{
            padding: "28px 30px", background: theme.bgSoft,
            border: `1px dashed ${theme.hair}`,
            fontFamily: theme.mono, fontSize: 12, color: theme.inkFaint,
            letterSpacing: "0.18em", textTransform: "uppercase",
          }}>loading…</div>
        ) : items.length === 0 ? (
          <EmptyState/>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {items.map((a) => (
              <ApprovalRow key={a.id} approval={a} agentName={agentName(a.agent_id)}/>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}

function EmptyState() {
  return (
    <div style={{
      padding: "48px 40px", background: theme.bgSoft,
      border: `1px dashed ${theme.hair}`,
      textAlign: "center", maxWidth: 560, margin: "0 auto",
    }}>
      <div style={{
        fontFamily: theme.display, fontStyle: "italic", fontWeight: 500,
        fontSize: 28, color: theme.inkLede, letterSpacing: "-0.015em", marginBottom: 14,
      }}>
        Nothing waiting on you.
      </div>
      <div style={{
        fontFamily: theme.body, fontSize: 14, color: theme.inkDim, lineHeight: 1.55,
      }}>
        When an agent stages a high-stakes action — sending an email, spending money,
        editing a record outside its lane — it'll land here. The page polls every 10s.
      </div>
    </div>
  );
}

function ApprovalRow({ approval, agentName }: { approval: Approval; agentName: string }) {
  return (
    <div style={{
      padding: "18px 22px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      display: "grid", gridTemplateColumns: "1fr auto", gap: 18, alignItems: "center",
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.accent,
          letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6,
        }}>{approval.kind} · {agentName}</div>
        <div style={{
          fontFamily: theme.body, fontSize: 15, color: theme.ink, lineHeight: 1.45,
        }}>{approval.summary}</div>
        <div style={{
          marginTop: 6, fontFamily: theme.mono, fontSize: 11,
          color: theme.inkFaint, letterSpacing: "0.12em",
        }}>{new Date(approval.created_at).toLocaleString()}</div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button disabled style={{ ...secondaryBtn, opacity: 0.5 }} title="Backend endpoint not yet wired">
          Reject
        </button>
        <button disabled style={{ ...primaryBtn, opacity: 0.5 }} title="Backend endpoint not yet wired">
          Approve
        </button>
      </div>
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 13,
  padding: "8px 18px", borderRadius: 999, cursor: "pointer",
};

const secondaryBtn: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "8px 14px", borderRadius: 999, cursor: "pointer",
};
