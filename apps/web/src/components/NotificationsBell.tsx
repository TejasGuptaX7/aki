"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { theme } from "@/lib/theme";
import { useAgents } from "@/lib/agents";
import { notificationsApi, Notification } from "@/lib/api";

/**
 * Fixed top-right bell. Polls /notifications?dismissed=false every 15s;
 * click opens a panel that lets the user dismiss rows individually. The
 * sidebar already covers /approvals (blocking decisions); this is the
 * non-blocking inbox — "I finished the report", "I'm stuck on X".
 */
export function NotificationsBell() {
  const { getToken, isSignedIn } = useAuth();
  const { agents } = useAgents();
  const [items, setItems] = React.useState<Notification[]>([]);
  const [open, setOpen] = React.useState(false);
  const [pending, setPending] = React.useState<Record<string, boolean>>({});
  const ref = React.useRef<HTMLDivElement | null>(null);

  const tok = React.useCallback(
    () => getToken({ template: "aki" }),
    [getToken],
  );

  React.useEffect(() => {
    if (!isSignedIn) return;
    let mounted = true;
    const tick = async () => {
      try {
        const list = await notificationsApi.list(tok, { dismissed: false, limit: 50 });
        if (mounted) setItems(list);
      } catch {
        /* keep prior list on transient failure — the bell shouldn't error */
      }
    };
    tick();
    const id = setInterval(tick, 15_000);
    return () => { mounted = false; clearInterval(id); };
  }, [tok, isSignedIn]);

  // Close on outside click.
  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const agentName = React.useCallback(
    (id: string | null) => {
      if (!id) return null;
      return agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);
    },
    [agents],
  );

  const dismiss = async (n: Notification) => {
    setPending((p) => ({ ...p, [n.id]: true }));
    // Optimistic: remove from the list immediately.
    setItems((curr) => curr.filter((x) => x.id !== n.id));
    try {
      await notificationsApi.dismiss(tok, n.id);
    } catch {
      // Restore the row if the dismiss failed.
      setItems((curr) => [n, ...curr.filter((x) => x.id !== n.id)]);
    } finally {
      setPending((p) => { const next = { ...p }; delete next[n.id]; return next; });
    }
  };

  if (!isSignedIn) return null;

  const count = items.length;

  return (
    <div ref={ref} style={{
      position: "fixed", top: 18, right: 24, zIndex: 50,
    }}>
      <button
        aria-label="notifications"
        onClick={() => setOpen((v) => !v)}
        style={{
          position: "relative",
          width: 38, height: 38, borderRadius: "50%",
          background: open ? theme.bgSoft : "transparent",
          border: `1px solid ${theme.hair}`,
          color: theme.inkLede, cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <BellIcon/>
        {count > 0 && (
          <span style={{
            position: "absolute", top: -2, right: -2,
            minWidth: 18, height: 18, padding: "0 5px",
            fontFamily: theme.mono, fontSize: 10, fontWeight: 600,
            background: theme.accent, color: theme.bg,
            borderRadius: 999, lineHeight: "18px", textAlign: "center",
          }}>{count > 99 ? "99+" : count}</span>
        )}
      </button>

      {open && (
        <div style={{
          position: "absolute", top: 48, right: 0,
          width: 380, maxHeight: "min(70vh, 560px)",
          background: theme.bg, border: `1px solid ${theme.hair}`,
          borderRadius: 8, overflow: "hidden",
          boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
          display: "flex", flexDirection: "column",
        }}>
          <div style={{
            padding: "14px 18px", borderBottom: `1px solid ${theme.hair}`,
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <span style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.22em", textTransform: "uppercase",
            }}>notifications</span>
            <div style={{ flex: 1 }}/>
            {count > 0 && (
              <span style={{
                fontFamily: theme.mono, fontSize: 11, color: theme.inkDim,
              }}>{count} unread</span>
            )}
          </div>

          <div style={{ overflowY: "auto", flex: 1 }}>
            {count === 0 ? (
              <div style={{
                padding: "40px 24px", textAlign: "center",
                fontFamily: theme.body, fontSize: 13, color: theme.inkDim, lineHeight: 1.55,
              }}>
                Nothing in the inbox.<br/>
                <span style={{ color: theme.inkFaint, fontSize: 12 }}>
                  Polls every 15s.
                </span>
              </div>
            ) : (
              items.map((n) => (
                <Row
                  key={n.id}
                  n={n}
                  agentName={agentName(n.agent_id)}
                  busy={!!pending[n.id]}
                  onDismiss={() => dismiss(n)}
                  onNavigate={() => setOpen(false)}
                />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ n, agentName, busy, onDismiss, onNavigate }: {
  n: Notification;
  agentName: string | null;
  busy: boolean;
  onDismiss: () => void;
  onNavigate: () => void;
}) {
  const kindColor =
    n.kind === "error" ? "#ee5959"
    : n.kind === "done" ? theme.accent
    : theme.inkLede;

  const inner = (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 10, color: kindColor,
        letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 4,
      }}>
        {n.kind}{agentName && <> · {agentName}</>}
      </div>
      <div style={{
        fontFamily: theme.body, fontSize: 14, color: theme.ink,
        fontWeight: 500, lineHeight: 1.4, marginBottom: 4,
      }}>{n.title}</div>
      {n.body && (
        <div style={{
          fontFamily: theme.body, fontSize: 13, color: theme.inkLede,
          lineHeight: 1.5, overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
        }}>{n.body}</div>
      )}
      <div style={{
        marginTop: 6, fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
        letterSpacing: "0.12em",
      }}>{new Date(n.created_at).toLocaleString()}</div>
    </div>
  );

  return (
    <div style={{
      padding: "14px 18px", borderBottom: `1px solid ${theme.hairSoft}`,
      display: "flex", alignItems: "flex-start", gap: 10,
      opacity: busy ? 0.5 : 1, transition: "opacity 0.15s ease",
    }}>
      {n.agent_id ? (
        <Link
          href={`/agents/${n.agent_id}/runs`}
          onClick={onNavigate}
          style={{ textDecoration: "none", color: "inherit", flex: 1, minWidth: 0 }}
        >{inner}</Link>
      ) : inner}

      <button
        onClick={onDismiss}
        disabled={busy}
        aria-label="dismiss"
        style={{
          background: "transparent", border: "none", cursor: "pointer",
          color: theme.inkFaint, fontFamily: theme.mono, fontSize: 16,
          padding: "2px 6px", lineHeight: 1, flexShrink: 0,
        }}
      >×</button>
    </div>
  );
}

function BellIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>
    </svg>
  );
}
