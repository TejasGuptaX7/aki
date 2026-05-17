"use client";

import * as React from "react";
import { theme } from "@/lib/theme";
import { useAuthToken } from "@/lib/agents";
import { agentsApi, AgentRun, AgentRunStep, ApiError } from "@/lib/api";

/**
 * Plan-and-execute checklist that sits above the chat thread. Polls
 * /agents/{id}/current-run every 3 seconds while the surface is open.
 * Renders nothing when there's no active run or the endpoint isn't
 * shipped — the chat surface stays clean.
 */
export function PlanScroll({ agentId }: { agentId: string }) {
  const tok = useAuthToken();
  const [run, setRun] = React.useState<AgentRun | null>(null);
  const [collapsed, setCollapsed] = React.useState(false);

  React.useEffect(() => {
    let mounted = true;
    setRun(null);
    setCollapsed(false);

    const tick = async () => {
      try {
        const r = await agentsApi.currentRun(tok, agentId);
        if (mounted) setRun(r);
      } catch (e) {
        if (!mounted) return;
        // 404 or 204 both mean "no active run" — clear and keep polling
        // quietly. Other errors silently swallow so we never crowd the
        // chat surface with infra noise the user can't act on.
        if (e instanceof ApiError && (e.status === 404 || e.status === 204)) {
          setRun(null);
        }
      }
    };
    tick();
    const id = setInterval(tick, 3_000);
    return () => { mounted = false; clearInterval(id); };
  }, [tok, agentId]);

  if (!run || run.plan.length === 0) return null;

  const total = run.plan.length;
  const done = run.plan.filter((s) => s.status === "done").length;
  const active = run.plan.find((s, i) => s.status === "active" || i === run.current_index);
  const errored = run.plan.some((s) => s.status === "errored");

  return (
    <div style={{
      marginBottom: 24, padding: "14px 18px",
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      borderLeft: `2px solid ${errored ? "#ee5959" : theme.accent}`,
    }}>
      <button
        onClick={() => setCollapsed((c) => !c)}
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          width: "100%", padding: 0, background: "transparent",
          border: "none", cursor: "pointer", color: theme.ink,
          textAlign: "left", gap: 14,
        }}
        aria-expanded={!collapsed}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <Pulse errored={errored}/>
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.accent,
              letterSpacing: "0.22em", textTransform: "uppercase",
            }}>
              plan · {done}/{total}
            </div>
            <div style={{
              marginTop: 3, fontFamily: theme.body, fontSize: 14,
              color: theme.ink, lineHeight: 1.4,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {active?.text ?? run.plan[run.plan.length - 1]?.text ?? "Working…"}
            </div>
          </div>
        </div>
        <Chevron collapsed={collapsed}/>
      </button>

      {!collapsed && (
        <ol style={{
          marginTop: 14, padding: 0, listStyle: "none",
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          {run.plan.map((step, i) => (
            <Step key={i} step={step} index={i} isActive={i === run.current_index}/>
          ))}
        </ol>
      )}
    </div>
  );
}

function Step({ step, index, isActive }: {
  step: AgentRunStep; index: number; isActive: boolean;
}) {
  const status = step.status ?? (isActive ? "active" : "pending");
  return (
    <li style={{
      display: "grid", gridTemplateColumns: "22px 1fr",
      gap: 12, alignItems: "flex-start",
    }}>
      <Marker status={status}/>
      <div style={{
        fontFamily: theme.body, fontSize: 13,
        color: status === "done" ? theme.inkFaint
          : status === "errored" ? "#ee5959"
          : status === "active" ? theme.ink
          : theme.inkDim,
        lineHeight: 1.5,
        textDecoration: status === "done" ? "line-through" : "none",
      }}>
        {step.text}
      </div>
    </li>
  );
}

function Marker({ status }: { status: AgentRunStep["status"] }) {
  if (status === "done") {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" style={{ marginTop: 4 }}>
        <circle cx="7" cy="7" r="6" fill="none" stroke={theme.accent} strokeWidth="1.2" opacity="0.5"/>
        <path d="M4 7.4l2 2 4-4.4" fill="none" stroke={theme.accent} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  }
  if (status === "errored") {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" style={{ marginTop: 4 }}>
        <circle cx="7" cy="7" r="6" fill="none" stroke="#ee5959" strokeWidth="1.2"/>
        <path d="M5 5l4 4M9 5l-4 4" stroke="#ee5959" strokeWidth="1.4" strokeLinecap="round"/>
      </svg>
    );
  }
  if (status === "active") {
    return (
      <span style={{
        display: "inline-block", width: 10, height: 10, marginTop: 6,
        marginLeft: 2, borderRadius: "50%", background: theme.accent,
        animation: "akiPulse 1.4s ease-in-out infinite",
      }}/>
    );
  }
  // pending
  return (
    <span style={{
      display: "inline-block", width: 10, height: 10, marginTop: 6,
      marginLeft: 2, borderRadius: "50%",
      border: `1px solid ${theme.hair}`,
    }}/>
  );
}

function Pulse({ errored }: { errored: boolean }) {
  const c = errored ? "#ee5959" : theme.accent;
  return (
    <span style={{
      width: 8, height: 8, borderRadius: "50%", background: c,
      animation: errored ? "none" : "akiPulse 1.4s ease-in-out infinite",
      flexShrink: 0,
    }}/>
  );
}

function Chevron({ collapsed }: { collapsed: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" style={{
      transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
      transition: "transform 0.15s ease",
      color: theme.inkDim, flexShrink: 0,
    }}>
      <path d="M3 5l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
