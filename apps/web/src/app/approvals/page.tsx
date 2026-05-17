"use client";

import * as React from "react";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { approvalsApi, Approval } from "@/lib/api";

/**
 * Approvals inbox. Polls GET /approvals every 10s; Approve / Deny
 * dispatch to /approvals/{id}/approve and /approvals/{id}/deny and
 * optimistically remove the row from the list. On failure we restore
 * the row and surface the error.
 */
export default function ApprovalsPage() {
  const tok = useAuthToken();
  const { agents } = useAgents();
  const [items, setItems] = React.useState<Approval[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  // Rows currently being acted on — disables both buttons + dims the row
  // while the request is in flight so users don't double-click.
  const [pending, setPending] = React.useState<Record<string, "approve" | "deny" | undefined>>({});

  const refetch = React.useCallback(async () => {
    try {
      const list = await approvalsApi.list(tok);
      setItems(list);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [tok]);

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

  const decide = React.useCallback(async (approval: Approval, decision: "approve" | "deny") => {
    setErr(null);
    setPending((p) => ({ ...p, [approval.id]: decision }));

    // Optimistically remove from the list — the agent runtime moves on
    // immediately on the server side, so the row shouldn't linger.
    const snapshot = items;
    setItems((curr) => curr?.filter((x) => x.id !== approval.id) ?? curr);

    try {
      if (decision === "approve") await approvalsApi.approve(tok, approval.id);
      else await approvalsApi.deny(tok, approval.id);
      // Refetch in the background to pick up any new rows the polling
      // tick might've missed, but don't await — we already updated the UI.
      refetch();
    } catch (e) {
      setItems(snapshot ?? null);
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPending((p) => {
        const next = { ...p };
        delete next[approval.id];
        return next;
      });
    }
  }, [tok, items, refetch]);

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
              <ApprovalRow key={a.id}
                approval={a}
                agentName={agentName(a.agent_id)}
                pending={pending[a.id]}
                onDecide={(decision) => decide(a, decision)}/>
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

function ApprovalRow({ approval, agentName, pending, onDecide }: {
  approval: Approval;
  agentName: string;
  pending: "approve" | "deny" | undefined;
  onDecide: (decision: "approve" | "deny") => void;
}) {
  const busy = pending !== undefined;
  return (
    <div style={{
      padding: "18px 22px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      display: "grid", gridTemplateColumns: "1fr auto", gap: 18, alignItems: "center",
      opacity: busy ? 0.55 : 1,
      transition: "opacity 0.15s ease",
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
        <button
          onClick={() => onDecide("deny")}
          disabled={busy}
          style={{ ...secondaryBtn, cursor: busy ? "default" : "pointer" }}
        >
          {pending === "deny" ? "Rejecting…" : "Reject"}
        </button>
        <button
          onClick={() => onDecide("approve")}
          disabled={busy}
          style={{ ...primaryBtn, cursor: busy ? "default" : "pointer" }}
        >
          {pending === "approve" ? "Approving…" : "Approve"}
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
