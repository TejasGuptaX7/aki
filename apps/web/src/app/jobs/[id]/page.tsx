"use client";

import * as React from "react";
import { use as usePromise } from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";

type Job = {
  id: string;
  brief: string;
  status: string;
  schedule_cron: string | null;
  result_summary: string | null;
  cost_usd: number;
  brain_source_id: string | null;
  created_at: string;
  updated_at: string;
};

type Event = {
  id: number;
  kind: string;
  ts: string;
  payload: Record<string, unknown>;
};

export default function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = usePromise(params);
  const { getToken } = useAuth();
  const [job, setJob] = React.useState<Job | null>(null);
  const [events, setEvents] = React.useState<Event[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const [cancelling, setCancelling] = React.useState(false);

  // Initial job fetch.
  React.useEffect(() => {
    (async () => {
      try {
        const token = await getToken({ template: "aki" });
        const r = await fetch(`${API_URL}/v1/jobs/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!r.ok) throw new Error(`job ${r.status}: ${await r.text()}`);
        setJob(await r.json());
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [id, getToken]);

  // SSE event stream. Reconnects on close as long as the job isn't terminal.
  React.useEffect(() => {
    if (!job) return;
    if (["done", "failed", "cancelled"].includes(job.status)) return;

    let cancelled = false;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

    (async () => {
      try {
        const token = await getToken({ template: "aki" });
        const r = await fetch(`${API_URL}/v1/jobs/${id}/events`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!r.ok || !r.body) throw new Error(`events ${r.status}`);
        reader = r.body.getReader();
        const decoder = new TextDecoder();
        let tail = "";
        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          tail += decoder.decode(value, { stream: true });
          let sep;
          while ((sep = tail.indexOf("\n\n")) !== -1) {
            const block = tail.slice(0, sep);
            tail = tail.slice(sep + 2);
            const data: string[] = [];
            let evt = "message";
            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) evt = line.slice(6).trim();
              else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
            }
            if (!data.length) continue;
            try {
              const obj = JSON.parse(data.join("\n"));
              if (evt === "end") {
                setJob((j) => j ? { ...j, status: (obj.status as string) || j.status } : j);
              } else {
                setEvents((curr) => [...curr, obj]);
              }
            } catch {/* ignore */}
          }
        }
      } catch (e: unknown) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      try { reader?.cancel(); } catch {/* ignore */}
    };
  }, [id, job?.status, getToken]);

  async function cancel() {
    setCancelling(true);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/jobs/${id}/cancel`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`cancel ${r.status}`);
      setJob((j) => j ? { ...j, status: "cancelled" } : j);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  }

  return (
    <AppShell>
      <SectionHeader
        kicker={`brief · ${id.slice(0, 8)}`}
        title={
          job ? (
            <span style={{ fontStyle: "italic", fontWeight: 500 }}>
              {job.brief.split("\n")[0].slice(0, 80)}
            </span>
          ) : "Loading…"
        }
        lede={
          job ? (
            <span style={{ fontFamily: theme.mono, fontSize: 12, letterSpacing: "0.16em" }}>
              {job.status.toUpperCase()} · ${job.cost_usd.toFixed(4)} ·{" "}
              {new Date(job.created_at).toLocaleString()}
            </span>
          ) : undefined
        }
      />
      <div style={{ padding: "32px 56px", display: "grid", gridTemplateColumns: "1fr 360px", gap: 40 }}>
        <div>
          {err && <ErrorBanner>{err}</ErrorBanner>}
          {job?.result_summary && (
            <section style={{ marginBottom: 36 }}>
              <Kicker>summary</Kicker>
              <div style={{ marginTop: 12, padding: "20px 24px",
                            background: theme.bgSoft, border: `1px solid ${theme.hair}`,
                            fontFamily: theme.body, fontSize: 15, lineHeight: 1.55, color: theme.ink,
                            whiteSpace: "pre-wrap" }}>
                {job.result_summary}
              </div>
            </section>
          )}
          <section>
            <Kicker>live feed</Kicker>
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
              {events.length === 0 && <Empty>No events yet.</Empty>}
              {events.map((ev) => <EventRow key={ev.id} ev={ev}/>)}
            </div>
          </section>
        </div>
        <aside>
          <Kicker>brief</Kicker>
          <div style={{ marginTop: 12, padding: "16px 18px",
                        background: theme.bgSoft, border: `1px solid ${theme.hair}`,
                        fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
                        whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
            {job?.brief}
          </div>
          {job && !["done", "failed", "cancelled"].includes(job.status) && (
            <button onClick={cancel} disabled={cancelling} style={{
              marginTop: 20, width: "100%",
              background: "transparent", color: "#ee5959",
              border: "1px solid rgba(238,89,89,0.32)",
              padding: "10px 16px", fontFamily: theme.body, fontSize: 13,
              cursor: cancelling ? "default" : "pointer", borderRadius: 999,
            }}>
              {cancelling ? "Cancelling…" : "Cancel brief"}
            </button>
          )}
        </aside>
      </div>
    </AppShell>
  );
}

function EventRow({ ev }: { ev: Event }) {
  const tone =
    ev.kind === "tool_call" ? theme.accent :
    ev.kind === "error" ? "#ee5959" :
    ev.kind === "status_change" ? "#7ec8ff" :
    theme.inkDim;
  return (
    <div style={{
      padding: "10px 14px", background: theme.bg,
      border: `1px solid ${theme.hair}`, borderLeft: `2px solid ${tone}`,
      display: "grid", gridTemplateColumns: "100px 1fr 120px",
      gap: 12, alignItems: "baseline",
    }}>
      <span style={{ fontFamily: theme.mono, fontSize: 10, color: tone, letterSpacing: "0.18em", textTransform: "uppercase" }}>
        {ev.kind}
      </span>
      <span style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkLede, wordBreak: "break-all" }}>
        {summarize(ev)}
      </span>
      <span style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, textAlign: "right" }}>
        {new Date(ev.ts).toLocaleTimeString()}
      </span>
    </div>
  );
}

function summarize(ev: Event): string {
  const p = ev.payload || {};
  if (ev.kind === "tool_call") {
    return `${(p as any).tool ?? "tool"}${(p as any).label ? `: ${(p as any).label}` : ""}`;
  }
  if (ev.kind === "status_change") {
    return `→ ${(p as any).to ?? "?"}`;
  }
  if (ev.kind === "error") {
    return String((p as any).message ?? p);
  }
  return JSON.stringify(p).slice(0, 200);
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.22em", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "32px 16px", textAlign: "center",
      border: `1px dashed ${theme.hair}`,
      fontFamily: theme.body, fontSize: 13, color: theme.inkFaint,
    }}>
      {children}
    </div>
  );
}
