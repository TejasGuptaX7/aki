"use client";

import * as React from "react";
import Link from "next/link";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAuthToken } from "@/lib/agents";
import { agentsApi, schedulesApi, AgentDetail, AgentSchedule } from "@/lib/api";

/**
 * Full CRUD over /agents/{id}/schedules. Cron strings are validated
 * server-side (APScheduler's CronTrigger parser) — we surface the 400
 * message inline rather than re-parsing in the browser.
 */
export default function SchedulesPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params);
  const tok = useAuthToken();

  const [agent, setAgent] = React.useState<AgentDetail | null>(null);
  const [items, setItems] = React.useState<AgentSchedule[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  // Inline-create form.
  const [cron, setCron] = React.useState("0 9 * * *");
  const [prompt, setPrompt] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [createErr, setCreateErr] = React.useState<string | null>(null);

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

  const refetch = React.useCallback(async () => {
    try {
      const list = await schedulesApi.list(tok, agentId);
      setItems(list);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [tok, agentId]);

  React.useEffect(() => { refetch(); }, [refetch]);

  const create = async () => {
    const c = cron.trim(); const p = prompt.trim();
    if (!c || !p || creating) return;
    setCreating(true); setCreateErr(null);
    try {
      const row = await schedulesApi.create(tok, agentId, { cron: c, prompt: p, enabled: true });
      setItems((curr) => [row, ...(curr ?? [])]);
      setPrompt("");
    } catch (e) {
      setCreateErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const updateRow = async (
    id: string,
    body: { cron?: string; prompt?: string; enabled?: boolean },
  ) => {
    // Optimistic local edit; on failure, the next refetch reconciles.
    setItems((curr) => curr?.map((s) => s.id === id ? { ...s, ...body } as AgentSchedule : s) ?? curr);
    try {
      const updated = await schedulesApi.update(tok, agentId, id, body);
      setItems((curr) => curr?.map((s) => s.id === id ? updated : s) ?? curr);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      refetch();
    }
  };

  const removeRow = async (id: string) => {
    if (!window.confirm("Delete this schedule? It won't fire again.")) return;
    const snapshot = items;
    setItems((curr) => curr?.filter((s) => s.id !== id) ?? curr);
    try {
      await schedulesApi.remove(tok, agentId, id);
    } catch (e) {
      setItems(snapshot ?? null);
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <AppShell>
      <SectionHeader
        kicker={`/00 · agent · ${agent?.slug ?? "…"} · schedules`}
        title={<>Schedules <em style={{ fontStyle: "italic", fontWeight: 500 }}>for {agent?.name ?? "…"}</em></>}
        lede="Cron-driven runs. Each entry fires a new agent run on its UTC cron expression with the prompt you set. Toggle enabled to pause without losing the row."
        right={
          <div style={{ display: "flex", gap: 10 }}>
            <Link href={`/agents/${agentId}`} style={secondaryBtn}>Edit brief</Link>
            <Link href={`/agents/${agentId}/runs`} style={secondaryBtn}>Runs</Link>
            <Link href={`/chat/${agentId}`} style={secondaryBtn}>Open chat</Link>
          </div>
        }
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      <section style={{ padding: "32px 56px 24px" }}>
        <Label>new schedule</Label>
        <div style={{
          padding: "20px 22px", background: theme.bgSoft,
          border: `1px solid ${theme.hair}`,
          display: "flex", flexDirection: "column", gap: 14,
        }}>
          <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 14 }}>
            <div>
              <SubLabel>cron · utc</SubLabel>
              <input
                value={cron}
                onChange={(e) => setCron(e.target.value)}
                placeholder="0 9 * * *"
                style={{ ...inputStyle, fontFamily: theme.mono, fontSize: 13 }}
              />
              <CronHints onPick={setCron}/>
            </div>
            <div>
              <SubLabel>prompt</SubLabel>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                placeholder="What should the agent do on each fire?"
                style={{ ...inputStyle, fontSize: 14, lineHeight: 1.5, resize: "vertical" }}
              />
            </div>
          </div>
          {createErr && (
            <div style={{
              padding: "10px 14px",
              background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)",
              color: "#ee5959", fontFamily: theme.mono, fontSize: 12,
            }}>{createErr}</div>
          )}
          <div>
            <button
              onClick={create}
              disabled={creating || !cron.trim() || !prompt.trim()}
              style={{ ...primaryBtn, opacity: (creating || !cron.trim() || !prompt.trim()) ? 0.5 : 1 }}
            >
              {creating ? "Creating…" : "Create schedule"}
            </button>
          </div>
        </div>
      </section>

      <section style={{ padding: "16px 56px 64px" }}>
        <Label>existing</Label>
        {items === null ? (
          <div style={emptyCardStyle}>loading…</div>
        ) : items.length === 0 ? (
          <div style={emptyCardStyle}>no schedules yet</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {items.map((s) => (
              <ScheduleRow
                key={s.id}
                row={s}
                onUpdate={(body) => updateRow(s.id, body)}
                onDelete={() => removeRow(s.id)}
              />
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}

function ScheduleRow({ row, onUpdate, onDelete }: {
  row: AgentSchedule;
  onUpdate: (body: { cron?: string; prompt?: string; enabled?: boolean }) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [cron, setCron] = React.useState(row.cron);
  const [prompt, setPrompt] = React.useState(row.prompt);
  const [saving, setSaving] = React.useState(false);
  const [toggling, setToggling] = React.useState(false);
  const [rowErr, setRowErr] = React.useState<string | null>(null);

  React.useEffect(() => {
    // Sync local edit state when the row changes from the outside (refetch).
    if (!editing) { setCron(row.cron); setPrompt(row.prompt); }
  }, [row.cron, row.prompt, editing]);

  const dirty = cron.trim() !== row.cron || prompt.trim() !== row.prompt;

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true); setRowErr(null);
    try {
      const body: { cron?: string; prompt?: string } = {};
      if (cron.trim() !== row.cron) body.cron = cron.trim();
      if (prompt.trim() !== row.prompt) body.prompt = prompt.trim();
      await onUpdate(body);
      setEditing(false);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async () => {
    setToggling(true); setRowErr(null);
    try {
      await onUpdate({ enabled: !row.enabled });
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : String(e));
    } finally {
      setToggling(false);
    }
  };

  return (
    <div style={{
      padding: "18px 22px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      display: "flex", flexDirection: "column", gap: 14,
      opacity: row.enabled ? 1 : 0.65,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span style={{
          fontFamily: theme.mono, fontSize: 10,
          color: row.enabled ? theme.accent : theme.inkDim,
          letterSpacing: "0.22em", textTransform: "uppercase",
        }}>{row.enabled ? "enabled" : "paused"}</span>
        {!editing && (
          <code style={{
            fontFamily: theme.mono, fontSize: 13, color: theme.ink,
            padding: "2px 10px", background: "rgba(241,237,224,0.06)",
            borderRadius: 4,
          }}>{row.cron}</code>
        )}
        <span style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.12em",
        }}>
          {row.next_run_at
            ? `next ${new Date(row.next_run_at).toLocaleString()}`
            : "next —"}
          {row.last_run_at && ` · last ${new Date(row.last_run_at).toLocaleString()}`}
        </span>
        <div style={{ flex: 1 }}/>
        <button onClick={toggle} disabled={toggling} style={secondaryBtnSm}>
          {toggling ? "…" : row.enabled ? "Pause" : "Resume"}
        </button>
        <button onClick={() => setEditing((v) => !v)} style={secondaryBtnSm}>
          {editing ? "Cancel" : "Edit"}
        </button>
        <button onClick={onDelete} style={dangerBtn}>Delete</button>
      </div>

      {editing ? (
        <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 14 }}>
          <div>
            <SubLabel>cron · utc</SubLabel>
            <input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              style={{ ...inputStyle, fontFamily: theme.mono, fontSize: 13 }}
            />
            <CronHints onPick={setCron}/>
          </div>
          <div>
            <SubLabel>prompt</SubLabel>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              style={{ ...inputStyle, fontSize: 14, lineHeight: 1.5, resize: "vertical" }}
            />
            <div style={{ marginTop: 10, display: "flex", gap: 10 }}>
              <button
                onClick={save}
                disabled={!dirty || saving}
                style={{ ...primaryBtnSm, opacity: !dirty || saving ? 0.5 : 1 }}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{
          fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
          lineHeight: 1.5, whiteSpace: "pre-wrap",
        }}>{row.prompt}</div>
      )}

      {rowErr && (
        <div style={{
          padding: "10px 14px",
          background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)",
          color: "#ee5959", fontFamily: theme.mono, fontSize: 12,
        }}>{rowErr}</div>
      )}
    </div>
  );
}

const CRON_HINTS: { label: string; value: string }[] = [
  { label: "every hour", value: "0 * * * *" },
  { label: "daily 9 utc", value: "0 9 * * *" },
  { label: "weekdays 9 utc", value: "0 9 * * 1-5" },
  { label: "weekly mon 13 utc", value: "0 13 * * 1" },
];

function CronHints({ onPick }: { onPick: (v: string) => void }) {
  return (
    <div style={{
      marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6,
    }}>
      {CRON_HINTS.map((h) => (
        <button
          key={h.value}
          type="button"
          onClick={() => onPick(h.value)}
          style={{
            fontFamily: theme.mono, fontSize: 10, color: theme.inkDim,
            background: "transparent", border: `1px solid ${theme.hair}`,
            padding: "3px 8px", borderRadius: 999, cursor: "pointer",
            letterSpacing: "0.08em",
          }}
        >{h.label}</button>
      ))}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 10,
    }}>{children}</div>
  );
}

function SubLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6,
    }}>{children}</div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", background: theme.bg, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "10px 12px", fontFamily: theme.body, fontSize: 14,
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

const primaryBtnSm: React.CSSProperties = {
  ...primaryBtn, padding: "8px 16px", fontSize: 12,
};

const secondaryBtn: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "10px 18px", borderRadius: 999, cursor: "pointer",
  textDecoration: "none", display: "inline-flex", alignItems: "center",
};

const secondaryBtnSm: React.CSSProperties = {
  ...secondaryBtn, padding: "6px 14px", fontSize: 12,
};

const dangerBtn: React.CSSProperties = {
  background: "transparent", color: "#ee5959",
  border: "1px solid rgba(238,89,89,0.32)",
  fontFamily: theme.body, fontWeight: 500, fontSize: 12,
  padding: "6px 14px", borderRadius: 999, cursor: "pointer",
};
