"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";

type Job = {
  id: string;
  department_id: string;
  actor: string;
  brief: string;
  status: string;
  schedule_cron: string | null;
  result_summary: string | null;
  cost_usd: number;
  created_at: string;
  updated_at: string;
};

export default function JobsPage() {
  const { getToken } = useAuth();
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [showNew, setShowNew] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/jobs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`jobs ${r.status}: ${await r.text()}`);
      setJobs(await r.json());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => { refresh(); }, [refresh]);
  // Refresh every 5s while the page is open so newly-queued jobs surface.
  React.useEffect(() => {
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <AppShell>
      <SectionHeader
        kicker="jobs"
        title={<>Async briefs. <span style={{ fontStyle: "italic", fontWeight: 500, color: theme.inkDim }}>Run while you sleep.</span></>}
        lede="File a brief, close your laptop. Hermes runs it through the night and reports back."
      />
      <div style={{ padding: "32px 56px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
            {jobs.length} {jobs.length === 1 ? "brief" : "briefs"}
          </span>
          <button onClick={() => setShowNew(true)} style={primaryBtn}>
            New brief
          </button>
        </div>
        {err && <ErrorBanner>{err}</ErrorBanner>}
        {loading ? (
          <Empty>Loading…</Empty>
        ) : jobs.length === 0 ? (
          <Empty>
            No briefs yet. <button onClick={() => setShowNew(true)} style={linkBtn}>File one</button>.
          </Empty>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1, background: theme.hair }}>
            {jobs.map((j) => <JobRow key={j.id} job={j}/>)}
          </div>
        )}
      </div>
      {showNew && <NewJobModal onClose={() => { setShowNew(false); refresh(); }}/>}
    </AppShell>
  );
}

function JobRow({ job }: { job: Job }) {
  const subject = job.brief.split("\n")[0].slice(0, 110);
  return (
    <Link href={`/jobs/${job.id}`} style={{
      textDecoration: "none", color: "inherit",
      background: theme.bg, padding: "18px 20px",
      display: "grid", gridTemplateColumns: "120px 1fr 140px 100px", gap: 20,
      alignItems: "center",
    }}>
      <StatusPill status={job.status}/>
      <div style={{ fontFamily: theme.body, fontSize: 15, color: theme.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {subject}
      </div>
      <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.12em" }}>
        {formatTime(job.updated_at)}
      </div>
      <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, textAlign: "right" }}>
        ${job.cost_usd.toFixed(3)}
      </div>
    </Link>
  );
}

function StatusPill({ status }: { status: string }) {
  const color =
    status === "done" ? theme.accent :
    status === "running" ? "#7ec8ff" :
    status === "failed" ? "#ee5959" :
    status === "cancelled" ? theme.inkFaint :
    theme.inkDim;
  return (
    <span style={{
      fontFamily: theme.mono, fontSize: 10, letterSpacing: "0.22em",
      textTransform: "uppercase", color,
      borderLeft: `2px solid ${color}`, paddingLeft: 10,
    }}>
      {status}
    </span>
  );
}

function NewJobModal({ onClose }: { onClose: () => void }) {
  const { getToken } = useAuth();
  const [brief, setBrief] = React.useState("");
  const [departmentSlug, setDepartmentSlug] = React.useState("");
  const [cron, setCron] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  async function submit() {
    setErr(null);
    setSubmitting(true);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/jobs`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          brief,
          department_slug: departmentSlug || undefined,
          schedule_cron: cron || undefined,
        }),
      });
      if (!r.ok) throw new Error(`create ${r.status}: ${await r.text()}`);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: theme.bg, border: `1px solid ${theme.hair}`,
        padding: "32px 36px", width: 640, maxWidth: "90vw",
      }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 16 }}>
          new brief
        </div>
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="Describe the job in plain language. The agent will run it asynchronously and report back."
          rows={6}
          autoFocus
          style={{
            width: "100%", boxSizing: "border-box", resize: "vertical",
            background: theme.bgSoft, color: theme.ink, padding: "14px 16px",
            border: `1px solid ${theme.hair}`, borderRadius: 4,
            fontFamily: theme.body, fontSize: 15, lineHeight: 1.5, outline: "none",
          }}
        />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
          <input
            value={departmentSlug}
            onChange={(e) => setDepartmentSlug(e.target.value)}
            placeholder="department slug (optional)"
            style={inputStyle}
          />
          <input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            placeholder="cron, e.g. 0 9 * * 1-5 (optional)"
            style={inputStyle}
          />
        </div>
        {err && <ErrorBanner>{err}</ErrorBanner>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 20 }}>
          <button onClick={onClose} style={ghostBtn}>Cancel</button>
          <button onClick={submit} disabled={submitting || !brief.trim()} style={{
            ...primaryBtn,
            opacity: submitting || !brief.trim() ? 0.4 : 1,
            cursor: submitting ? "default" : "pointer",
          }}>
            {submitting ? "Filing…" : "File brief"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "80px 20px", textAlign: "center",
      border: `1px dashed ${theme.hair}`,
      fontFamily: theme.body, fontSize: 14, color: theme.inkDim,
    }}>
      {children}
    </div>
  );
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

const inputStyle: React.CSSProperties = {
  background: theme.bgSoft, color: theme.ink, padding: "10px 14px",
  border: `1px solid ${theme.hair}`, borderRadius: 4,
  fontFamily: theme.mono, fontSize: 13, outline: "none",
};

const primaryBtn: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 14,
  padding: "10px 22px", borderRadius: 999, cursor: "pointer",
};

const ghostBtn: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontSize: 14,
  padding: "10px 18px", borderRadius: 999, cursor: "pointer",
};

const linkBtn: React.CSSProperties = {
  background: "transparent", border: "none", padding: 0,
  color: theme.accent, fontFamily: theme.body, fontSize: 14,
  textDecoration: "underline", cursor: "pointer",
};
