"use client";

import * as React from "react";
import Link from "next/link";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAuthToken } from "@/lib/agents";
import { agentsApi, runsApi, AgentDetail, AgentRun } from "@/lib/api";

/**
 * Runs view: live tail of the current run (polled every 2s), plus the
 * recent-runs list and a "kick off" composer that POSTs /agents/{id}/runs.
 * Cancel only fires while status === "running"; idempotent on the server.
 */
export default function RunsPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params);
  const tok = useAuthToken();

  const [agent, setAgent] = React.useState<AgentDetail | null>(null);
  const [current, setCurrent] = React.useState<AgentRun | null>(null);
  const [runs, setRuns] = React.useState<AgentRun[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  const [prompt, setPrompt] = React.useState("");
  const [starting, setStarting] = React.useState(false);
  const [canceling, setCanceling] = React.useState(false);

  // Agent header data — one shot.
  React.useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const d = await agentsApi.get(tok, agentId);
        if (mounted) setAgent(d);
      } catch (e) {
        if (mounted) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { mounted = false; };
  }, [tok, agentId]);

  // Live tail. Polls /current-run on a 2s tick and refreshes the list on
  // a slower 6s tick. List refresh also fires immediately when the current
  // run flips terminal so the history reflects it without a wait.
  const lastStatusRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    let mounted = true;

    const tickCurrent = async () => {
      try {
        const c = await runsApi.current(tok, agentId);
        if (!mounted) return;
        setCurrent(c);
        const status = c?.status ?? null;
        if (lastStatusRef.current === "running" && status !== "running") {
          // running → terminal (or 404): force a list refresh.
          refreshList();
        }
        lastStatusRef.current = status;
        setErr(null);
      } catch (e) {
        if (mounted) setErr(e instanceof Error ? e.message : String(e));
      }
    };
    const refreshList = async () => {
      try {
        const rs = await runsApi.list(tok, agentId, 50);
        if (mounted) setRuns(rs);
      } catch {
        /* keep prior list on transient failure */
      }
    };

    tickCurrent();
    refreshList();
    const idC = setInterval(tickCurrent, 2_000);
    const idL = setInterval(refreshList, 6_000);
    return () => { mounted = false; clearInterval(idC); clearInterval(idL); };
  }, [tok, agentId]);

  const start = async () => {
    const text = prompt.trim();
    if (!text || starting) return;
    setStarting(true); setErr(null);
    try {
      await runsApi.start(tok, agentId, text);
      setPrompt("");
      // Optimistic: prime current with a placeholder until the first poll.
      setCurrent((c) => c ?? {
        id: "pending",
        agent_id: agentId,
        status: "running",
        plan: [],
        current_index: 0,
        prompt: text,
        started_at: new Date().toISOString(),
        completed_at: null,
        error: null,
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!current || current.id === "pending" || canceling) return;
    if (!window.confirm("Cancel this run?")) return;
    setCanceling(true); setErr(null);
    try {
      await runsApi.cancel(tok, agentId, current.id);
      // /current-run will return null on the next tick; nudge it now.
      const c = await runsApi.current(tok, agentId);
      setCurrent(c);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCanceling(false);
    }
  };

  return (
    <AppShell>
      <SectionHeader
        kicker={`/00 · agent · ${agent?.slug ?? "…"} · runs`}
        title={<>Runs <em style={{ fontStyle: "italic", fontWeight: 500 }}>for {agent?.name ?? "…"}</em></>}
        lede="Each run is one long task — the prompt, the plan the agent declared, and how far it's gotten. The live tail polls /current-run every 2s."
        right={
          <div style={{ display: "flex", gap: 10 }}>
            <Link href={`/agents/${agentId}`} style={secondaryBtn}>Edit brief</Link>
            <Link href={`/agents/${agentId}/schedules`} style={secondaryBtn}>Schedules</Link>
            <Link href={`/chat/${agentId}`} style={secondaryBtn}>Open chat</Link>
          </div>
        }
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      <section style={{ padding: "32px 56px 24px" }}>
        <Label>kick off a run</Label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          placeholder="What should the agent do? It'll declare a plan and work through it."
          style={{ ...inputStyle, fontFamily: theme.body, fontSize: 14, lineHeight: 1.5, resize: "vertical" }}
        />
        <div style={{ marginTop: 10, display: "flex", gap: 12, alignItems: "center" }}>
          <button
            onClick={start}
            disabled={starting || !prompt.trim() || (current?.status === "running")}
            style={{ ...primaryBtn, opacity: (starting || !prompt.trim() || current?.status === "running") ? 0.5 : 1 }}
          >
            {starting ? "Starting…" : "Start run"}
          </button>
          {current?.status === "running" && (
            <span style={{
              fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
              letterSpacing: "0.18em", textTransform: "uppercase",
            }}>
              one run already in flight · cancel it to start another
            </span>
          )}
        </div>
      </section>

      <section style={{ padding: "16px 56px 24px" }}>
        <Label>current</Label>
        {current ? (
          <CurrentRunCard run={current} onCancel={cancel} canceling={canceling}/>
        ) : (
          <div style={emptyCardStyle}>idle · no run in progress</div>
        )}
      </section>

      <section style={{ padding: "16px 56px 64px" }}>
        <Label>history</Label>
        {runs === null ? (
          <div style={emptyCardStyle}>loading…</div>
        ) : runs.length === 0 ? (
          <div style={emptyCardStyle}>no runs yet · start one above</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {runs.map((r) => <RunRow key={r.id} run={r}/>)}
          </div>
        )}
      </section>
    </AppShell>
  );
}

function CurrentRunCard({ run, onCancel, canceling }: {
  run: AgentRun; onCancel: () => void; canceling: boolean;
}) {
  const isRunning = run.status === "running";
  const elapsed = run.started_at
    ? Math.max(0, Math.floor((Date.now() - new Date(run.started_at).getTime()) / 1000))
    : null;

  return (
    <div style={{
      padding: "20px 22px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      display: "flex", flexDirection: "column", gap: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <StatusDot status={run.status}/>
        <StatusPill status={run.status}/>
        <span style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.14em",
        }}>
          {run.plan.length > 0 ? `step ${Math.min(run.current_index + 1, run.plan.length)} of ${run.plan.length}` : "no plan yet"}
          {elapsed !== null && ` · ${formatElapsed(elapsed)} elapsed`}
        </span>
        <div style={{ flex: 1 }}/>
        {isRunning && run.id !== "pending" && (
          <button onClick={onCancel} disabled={canceling} style={dangerBtn}>
            {canceling ? "Canceling…" : "Cancel run"}
          </button>
        )}
      </div>

      <div style={{
        fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
        lineHeight: 1.5, whiteSpace: "pre-wrap",
      }}>{run.prompt}</div>

      {run.plan.length > 0 ? (
        <Plan plan={run.plan} currentIndex={run.current_index} runStatus={run.status}/>
      ) : (
        <div style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>waiting for the agent to declare a plan…</div>
      )}

      {run.error && (
        <div style={{
          padding: "10px 14px",
          background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)",
          color: "#ee5959", fontFamily: theme.mono, fontSize: 12,
        }}>{run.error}</div>
      )}
    </div>
  );
}

function Plan({ plan, currentIndex, runStatus }: {
  plan: AgentRun["plan"]; currentIndex: number; runStatus: AgentRun["status"];
}) {
  return (
    <ol style={{
      margin: 0, padding: 0, listStyle: "none",
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      {plan.map((step, i) => {
        const isCurrent = runStatus === "running" && i === currentIndex;
        const isDone = step.status === "done";
        return (
          <li key={i} style={{
            display: "flex", alignItems: "flex-start", gap: 12,
            padding: "8px 12px", borderRadius: 4,
            background: isCurrent ? "rgba(197,236,79,0.06)" : "transparent",
            borderLeft: `2px solid ${isCurrent ? theme.accent : "transparent"}`,
          }}>
            <span style={{
              fontFamily: theme.mono, fontSize: 11,
              color: isDone ? theme.accent : isCurrent ? theme.accent : theme.inkFaint,
              minWidth: 28, paddingTop: 1,
            }}>{isDone ? "✓" : isCurrent ? "→" : String(i + 1).padStart(2, "0")}</span>
            <span style={{
              fontFamily: theme.body, fontSize: 13,
              color: isDone ? theme.inkDim : isCurrent ? theme.ink : theme.inkLede,
              lineHeight: 1.5, flex: 1,
              textDecoration: isDone ? "line-through" : "none",
              textDecorationColor: theme.inkFaint,
            }}>{step.text || <em style={{ color: theme.inkFaint }}>(empty)</em>}</span>
          </li>
        );
      })}
    </ol>
  );
}

function RunRow({ run }: { run: AgentRun }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
    }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%", padding: "14px 22px",
          background: "transparent", border: "none", cursor: "pointer",
          textAlign: "left", color: theme.ink,
          display: "grid", gridTemplateColumns: "auto auto 1fr auto", gap: 14, alignItems: "center",
        }}
      >
        <StatusDot status={run.status}/>
        <StatusPill status={run.status}/>
        <span style={{
          fontFamily: theme.body, fontSize: 13, color: theme.inkLede,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0,
        }}>{run.prompt}</span>
        <span style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.12em",
        }}>{run.started_at ? new Date(run.started_at).toLocaleString() : "—"}</span>
      </button>
      {open && (
        <div style={{
          padding: "0 22px 18px", borderTop: `1px solid ${theme.hair}`,
          display: "flex", flexDirection: "column", gap: 12,
        }}>
          <div style={{ marginTop: 14, fontFamily: theme.body, fontSize: 14, color: theme.inkLede, whiteSpace: "pre-wrap" }}>
            {run.prompt}
          </div>
          {run.plan.length > 0 && (
            <Plan plan={run.plan} currentIndex={run.current_index} runStatus={run.status}/>
          )}
          {run.error && (
            <div style={{
              padding: "10px 14px",
              background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)",
              color: "#ee5959", fontFamily: theme.mono, fontSize: 12,
            }}>{run.error}</div>
          )}
          <div style={{
            fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.12em",
          }}>
            started {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
            {run.completed_at && ` · ended ${new Date(run.completed_at).toLocaleString()}`}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusDot({ status }: { status: AgentRun["status"] }) {
  const color =
    status === "running" ? theme.accent
    : status === "done" ? theme.accent
    : status === "errored" ? "#ee5959"
    : theme.inkFaint;
  return (
    <span style={{
      width: 8, height: 8, borderRadius: "50%", background: color,
      animation: status === "running" ? "akiPulse 1.4s ease-in-out infinite" : undefined,
      flexShrink: 0,
    }}/>
  );
}

function StatusPill({ status }: { status: AgentRun["status"] }) {
  const isErr = status === "errored";
  return (
    <span style={{
      fontFamily: theme.mono, fontSize: 10,
      color: isErr ? "#ee5959" : status === "running" || status === "done" ? theme.accent : theme.inkDim,
      letterSpacing: "0.22em", textTransform: "uppercase",
    }}>{status}</span>
  );
}

function formatElapsed(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m < 60) return `${m}m ${sec}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 10,
    }}>{children}</div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", background: theme.bgSoft, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "12px 14px", fontFamily: theme.body, fontSize: 15,
  outline: "none", boxSizing: "border-box",
};

const emptyCardStyle: React.CSSProperties = {
  padding: "22px 24px", background: theme.bgSoft,
  border: `1px dashed ${theme.hair}`,
  fontFamily: theme.mono, fontSize: 12, color: theme.inkFaint,
  letterSpacing: "0.18em", textTransform: "uppercase",
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
  textDecoration: "none", display: "inline-flex", alignItems: "center",
};

const dangerBtn: React.CSSProperties = {
  background: "transparent", color: "#ee5959",
  border: "1px solid rgba(238,89,89,0.32)",
  fontFamily: theme.body, fontWeight: 500, fontSize: 12,
  padding: "8px 16px", borderRadius: 999, cursor: "pointer",
};
