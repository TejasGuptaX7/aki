"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { AgentTabNav } from "@/components/AgentTabNav";
import { useAuthToken } from "@/lib/agents";
import {
  agentsApi, AgentMemory, ApiError, MemoryEntry,
} from "@/lib/api";

const ORG_CAP = 2200;
const USER_CAP = 1375;

/**
 * Brain tab — the agent's stored long-term memory across three files
 * Hermes reads at session start:
 *   SOUL.md   — identity / pinned persona, edited as one blob
 *   MEMORY.md — company-scope reminders (org)
 *   USER.md   — personal-to-the-logged-in-user reminders
 *
 * Memory is frozen at the start of every chat session, so any save shows
 * a "next run" banner — we explicitly don't promise instant pickup.
 */
export default function BrainPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params);
  const router = useRouter();
  const tok = useAuthToken();

  const [memory, setMemory] = React.useState<AgentMemory | null>(null);
  const [supported, setSupported] = React.useState(true);
  const [err, setErr] = React.useState<string | null>(null);
  const [savedAt, setSavedAt] = React.useState<number | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      const m = await agentsApi.getMemory(tok, agentId);
      setMemory(m);
      setErr(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // Could be the memory endpoints aren't shipped yet OR the agent
        // doesn't exist. Try the agent detail to disambiguate.
        try {
          await agentsApi.get(tok, agentId);
          setSupported(false);
          setMemory({ soul: "", org_entries: [], user_entries: [] });
        } catch {
          router.replace("/agents");
        }
        return;
      }
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [tok, agentId, router]);

  React.useEffect(() => { refresh(); }, [refresh]);

  function flash() {
    setSavedAt(Date.now());
    window.setTimeout(() => setSavedAt((t) => (t && Date.now() - t >= 4000 ? null : t)), 4100);
  }

  return (
    <AppShell>
      <SectionHeader
        kicker={`/00 · agent · brain`}
        title={<>What the agent <em style={{ fontStyle: "italic", fontWeight: 500 }}>remembers.</em></>}
        lede="Identity, shared reminders, and personal notes — the three files Hermes pulls on every session start."
        right={
          <div style={{ display: "flex", gap: 10 }}>
            <Link href={`/chat/${agentId}`} style={secondaryBtn}>Open chat</Link>
            <Link href={`/agents/${agentId}`} style={secondaryBtn}>Detail</Link>
          </div>
        }
      />

      <AgentTabNav agentId={agentId} current="brain"/>

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {!supported && (
        <div style={{
          margin: "16px 56px 0", padding: "8px 14px",
          background: theme.bgSoft, border: `1px dashed ${theme.hair}`,
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>
          memory endpoints not yet wired · edits will fail · check back after the next backend deploy
        </div>
      )}

      {savedAt && (
        <div style={{
          margin: "16px 56px 0", padding: "10px 18px",
          background: "rgba(197,236,79,0.08)", border: `1px solid ${theme.accentDim}`,
          color: theme.accent, fontFamily: theme.mono, fontSize: 12,
          letterSpacing: "0.08em",
        }}>
          Updated. Aki will pick this up on its next run.
        </div>
      )}

      {memory === null ? (
        <div style={{ padding: "48px 56px", fontFamily: theme.mono, fontSize: 12, color: theme.inkFaint }}>
          loading…
        </div>
      ) : (
        <section style={{
          padding: "32px 56px 80px", maxWidth: 920,
          display: "flex", flexDirection: "column", gap: 28,
        }}>
          <IdentityCard
            agentId={agentId}
            initial={memory.soul}
            disabled={!supported}
            onSaved={async (next) => {
              setMemory({ ...memory, soul: next.soul });
              flash();
            }}
            setErr={setErr}
          />
          <EntriesCard
            title="Company memory"
            kicker="memory.md · org-wide"
            blurb="Anyone on your team will see these. Things like 'we sell to Series-B B2B SaaS,' 'we never DM a candidate twice.'"
            scope="org"
            agentId={agentId}
            cap={ORG_CAP}
            disabled={!supported}
            entries={memory.org_entries}
            onChange={async () => { await refresh(); flash(); }}
            setErr={setErr}
          />
          <EntriesCard
            title="Personal memory"
            kicker="user.md · only you"
            blurb="Only your sessions with this agent see these. Things like 'I prefer terse replies,' 'always cc me on outbound.'"
            scope="user"
            agentId={agentId}
            cap={USER_CAP}
            disabled={!supported}
            entries={memory.user_entries}
            onChange={async () => { await refresh(); flash(); }}
            setErr={setErr}
          />
        </section>
      )}
    </AppShell>
  );
}

// ─── identity card (SOUL.md) ─────────────────────────────────────────

function IdentityCard({ agentId, initial, disabled, onSaved, setErr }: {
  agentId: string;
  initial: string;
  disabled: boolean;
  onSaved: (next: AgentMemory) => void;
  setErr: (s: string | null) => void;
}) {
  const tok = useAuthToken();
  const [value, setValue] = React.useState(initial);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => { setValue(initial); }, [initial]);

  const dirty = value !== initial;

  async function save() {
    if (!dirty || saving) return;
    setSaving(true); setErr(null);
    try {
      const next = await agentsApi.patchSoul(tok, agentId, value);
      onSaved(next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card kicker="soul.md · identity" title="Who this agent is">
      <p style={cardBlurb}>
        The agent&rsquo;s persona, voice, and the principles you want it to keep. Edit
        like a system-prompt addendum — there&rsquo;s no hard cap.
      </p>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        rows={14}
        placeholder="You are Aki Sales, a senior SDR…"
        style={{
          ...textareaStyle,
          fontFamily: theme.mono, fontSize: 13, lineHeight: 1.6, resize: "vertical",
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>{value.length.toLocaleString()} chars</span>
        <button onClick={save} disabled={!dirty || saving || disabled} style={{
          ...primaryBtn, opacity: (!dirty || saving || disabled) ? 0.5 : 1,
        }}>
          {saving ? "Saving…" : "Save identity"}
        </button>
      </div>
    </Card>
  );
}

// ─── entries cards (MEMORY.md / USER.md) ─────────────────────────────

function EntriesCard({
  title, kicker, blurb, scope, agentId, cap, disabled, entries, onChange, setErr,
}: {
  title: string;
  kicker: string;
  blurb: string;
  scope: "org" | "user";
  agentId: string;
  cap: number;
  disabled: boolean;
  entries: MemoryEntry[];
  onChange: () => Promise<void>;
  setErr: (s: string | null) => void;
}) {
  const tok = useAuthToken();
  const [adding, setAdding] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [savingNew, setSavingNew] = React.useState(false);

  const used = entries.reduce((n, e) => n + e.text.length, 0);
  const remaining = cap - used;
  const overCap = (draftLen: number) => used + draftLen > cap;

  async function add() {
    const text = draft.trim();
    if (!text || savingNew) return;
    if (overCap(text.length)) {
      setErr(`That entry would put ${scope === "org" ? "company" : "personal"} memory over the ${cap.toLocaleString()}-char cap.`);
      return;
    }
    setSavingNew(true); setErr(null);
    try {
      await agentsApi.addMemoryEntry(tok, agentId, { scope, text });
      setDraft("");
      setAdding(false);
      await onChange();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingNew(false);
    }
  }

  async function remove(id: string) {
    setBusyId(id); setErr(null);
    try {
      await agentsApi.removeMemoryEntry(tok, agentId, id);
      await onChange();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Card kicker={kicker} title={title}>
      <p style={cardBlurb}>{blurb}</p>

      <div style={{
        marginTop: 4, marginBottom: 14, display: "flex",
        justifyContent: "space-between", alignItems: "center", gap: 12,
      }}>
        <CapMeter used={used} cap={cap}/>
        <button
          onClick={() => { setAdding(true); setDraft(""); }}
          disabled={disabled || adding || remaining <= 0}
          style={{
            ...secondaryBtn,
            opacity: (disabled || adding || remaining <= 0) ? 0.5 : 1,
          }}
        >+ Add memory</button>
      </div>

      {adding && (
        <div style={{
          padding: "14px 16px", background: theme.bg,
          border: `1px solid ${theme.hair}`, marginBottom: 12,
        }}>
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add();
              if (e.key === "Escape") { setAdding(false); setDraft(""); }
            }}
            rows={3}
            placeholder={scope === "org"
              ? "We sell to Series-B B2B SaaS companies in NA and EU…"
              : "I prefer terse replies. CC me on every outbound."}
            disabled={savingNew}
            style={{
              ...textareaStyle,
              fontFamily: theme.body, fontSize: 14, lineHeight: 1.55, resize: "vertical",
              width: "100%", boxSizing: "border-box",
            }}
          />
          <div style={{
            marginTop: 10, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12,
          }}>
            <span style={{
              fontFamily: theme.mono, fontSize: 10,
              color: overCap(draft.length) ? "#ee5959" : theme.inkFaint,
              letterSpacing: "0.18em", textTransform: "uppercase",
            }}>
              {draft.length}/{remaining + draft.length} chars left
              {overCap(draft.length) && " · over cap"}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => { setAdding(false); setDraft(""); }}
                disabled={savingNew}
                style={secondaryBtn}
              >Cancel</button>
              <button
                onClick={add}
                disabled={savingNew || !draft.trim() || overCap(draft.length)}
                style={{
                  ...primaryBtn,
                  opacity: (savingNew || !draft.trim() || overCap(draft.length)) ? 0.5 : 1,
                }}
              >{savingNew ? "Saving…" : "Save memory"}</button>
            </div>
          </div>
        </div>
      )}

      {entries.length === 0 && !adding ? (
        <div style={{
          padding: "20px 22px", background: theme.bg,
          border: `1px dashed ${theme.hair}`,
          fontFamily: theme.body, fontSize: 13, color: theme.inkDim,
          fontStyle: "italic",
        }}>
          No entries yet.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {entries.map((entry) => (
            <EntryRow key={entry.id} entry={entry}
              busy={busyId === entry.id} disabled={disabled}
              onDelete={() => remove(entry.id)}/>
          ))}
        </div>
      )}
    </Card>
  );
}

function EntryRow({ entry, busy, disabled, onDelete }: {
  entry: MemoryEntry; busy: boolean; disabled: boolean; onDelete: () => void;
}) {
  return (
    <div style={{
      padding: "14px 16px", background: theme.bg,
      border: `1px solid ${theme.hair}`,
      display: "grid", gridTemplateColumns: "1fr auto", gap: 14, alignItems: "flex-start",
      opacity: busy ? 0.5 : 1,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{
          fontFamily: theme.body, fontSize: 14, color: theme.ink,
          lineHeight: 1.55, whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>{entry.text}</div>
        <div style={{
          marginTop: 8, fontFamily: theme.mono, fontSize: 10,
          color: theme.inkFaint, letterSpacing: "0.14em",
        }}>
          Aki added this on {new Date(entry.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
        </div>
      </div>
      <button
        onClick={onDelete}
        disabled={busy || disabled}
        style={{
          background: "transparent", color: theme.inkDim,
          border: `1px solid ${theme.hair}`,
          fontFamily: theme.body, fontSize: 11, fontWeight: 500,
          padding: "5px 12px", borderRadius: 999, cursor: busy ? "default" : "pointer",
          flexShrink: 0,
        }}
      >{busy ? "…" : "Delete"}</button>
    </div>
  );
}

function CapMeter({ used, cap }: { used: number; cap: number }) {
  const pct = Math.min(100, Math.round((used / cap) * 100));
  const color = used > cap ? "#ee5959" : pct > 85 ? "#ff9e3d" : theme.accent;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{
        width: 120, height: 4, background: "rgba(241,237,224,0.06)",
        overflow: "hidden",
      }}>
        <div style={{
          width: `${Math.min(100, pct)}%`, height: "100%", background: color,
          transition: "width 0.2s ease, background 0.2s ease",
        }}/>
      </div>
      <span style={{
        fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
        letterSpacing: "0.14em",
      }}>
        {used.toLocaleString()} / {cap.toLocaleString()}
      </span>
    </div>
  );
}

// ─── presentational ──────────────────────────────────────────────────

function Card({ kicker, title, children }: { kicker: string; title: string; children: React.ReactNode }) {
  return (
    <article style={{
      padding: "26px 28px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
    }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 10, color: theme.accent,
        letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 10,
      }}>{kicker}</div>
      <h2 style={{
        margin: 0, fontFamily: theme.display, fontWeight: 600, fontSize: 26,
        letterSpacing: "-0.02em", lineHeight: 1.15, color: theme.ink,
      }}>{title}</h2>
      {children}
    </article>
  );
}

const cardBlurb: React.CSSProperties = {
  margin: "10px 0 18px", fontFamily: theme.body, fontSize: 14,
  color: theme.inkLede, lineHeight: 1.55,
};

const textareaStyle: React.CSSProperties = {
  width: "100%", background: theme.bg, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "12px 14px", outline: "none", boxSizing: "border-box",
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
  padding: "9px 18px", borderRadius: 999, cursor: "pointer",
  textDecoration: "none", display: "inline-flex", alignItems: "center",
};
