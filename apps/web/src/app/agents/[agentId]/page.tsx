"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { agentsApi, ApiError, AgentDetail } from "@/lib/api";

export default function AgentDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params);
  const router = useRouter();
  const tok = useAuthToken();
  const { refresh } = useAgents();
  const [detail, setDetail] = React.useState<AgentDetail | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [name, setName] = React.useState("");
  const [sys, setSys] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);

  React.useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const d = await agentsApi.get(tok, agentId);
        if (!mounted) return;
        setDetail(d);
        setName(d.name);
        setSys(d.system_prompt);
      } catch (e) {
        if (mounted) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { mounted = false; };
  }, [tok, agentId]);

  async function save() {
    if (!detail) return;
    setSaving(true); setErr(null); setSaved(false);
    try {
      const updated = await agentsApi.update(tok, agentId, { name, system_prompt: sys });
      setDetail(updated);
      setSaved(true);
      await refresh();
      setTimeout(() => setSaved(false), 1800);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function archive() {
    if (!detail) return;
    if (!window.confirm(`Archive "${detail.name}"? Its memory and connections are preserved.`)) return;
    setDeleting(true); setErr(null);
    try {
      await agentsApi.remove(tok, agentId);
      await refresh();
      router.push("/agents");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setErr("Can't archive — this is your only active agent. Create another first.");
      } else {
        setErr(e instanceof Error ? e.message : String(e));
      }
      setDeleting(false);
    }
  }

  const dirty = detail !== null && (name !== detail.name || sys !== detail.system_prompt);

  return (
    <AppShell>
      <SectionHeader
        kicker={`/00 · agent · ${detail?.slug ?? "…"}`}
        title={detail ? detail.name : "…"}
        lede={detail ? `Created ${new Date(detail.created_at).toLocaleDateString()} · updated ${new Date(detail.updated_at).toLocaleDateString()}` : null}
        right={
          <div style={{ display: "flex", gap: 10 }}>
            <Link href={`/agents/${agentId}/runs`} style={secondaryBtn}>Runs</Link>
            <Link href={`/agents/${agentId}/schedules`} style={secondaryBtn}>Schedules</Link>
            <Link href={`/chat/${agentId}`} style={secondaryBtn}>Open chat</Link>
            <Link href={`/connect?agent_id=${agentId}`} style={secondaryBtn}>Connections</Link>
          </div>
        }
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      {!detail ? (
        <div style={{ padding: "48px 56px", fontFamily: theme.mono, fontSize: 12, color: theme.inkFaint }}>
          loading…
        </div>
      ) : (
        <section style={{ padding: "40px 56px 80px", maxWidth: 820 }}>
          <div style={{ marginBottom: 28 }}>
            <Label>name</Label>
            <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle}/>
          </div>

          <div style={{ marginBottom: 28 }}>
            <Label>brief / system prompt</Label>
            <textarea
              value={sys}
              onChange={(e) => setSys(e.target.value)}
              rows={18}
              style={{ ...inputStyle, fontFamily: theme.mono, fontSize: 13, lineHeight: 1.6, resize: "vertical" }}
            />
            <div style={{
              marginTop: 6, fontFamily: theme.mono, fontSize: 10,
              color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase",
            }}>
              this is what the agent sees on every turn · {sys.length} chars
            </div>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <button onClick={save} disabled={!dirty || saving} style={{ ...primaryBtn, opacity: !dirty || saving ? 0.5 : 1 }}>
              {saving ? "Saving…" : "Save changes"}
            </button>
            {saved && (
              <span style={{
                fontFamily: theme.mono, fontSize: 11, color: theme.accent,
                letterSpacing: "0.18em", textTransform: "uppercase",
              }}>saved</span>
            )}
            <div style={{ flex: 1 }}/>
            <button onClick={archive} disabled={deleting} style={dangerBtn}>
              {deleting ? "…" : "Archive agent"}
            </button>
          </div>
        </section>
      )}
    </AppShell>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 8,
    }}>{children}</div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", background: theme.bgSoft, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "12px 14px", fontFamily: theme.body, fontSize: 15,
  outline: "none", boxSizing: "border-box",
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
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "10px 18px", borderRadius: 999, cursor: "pointer",
};
