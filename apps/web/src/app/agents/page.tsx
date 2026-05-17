"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken, rememberAgent } from "@/lib/agents";
import { agentsApi, ApiError, AgentTemplate } from "@/lib/api";

export default function AgentsPage() {
  const router = useRouter();
  const { agents, status, error, refresh } = useAgents();
  const tok = useAuthToken();
  const [creating, setCreating] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [pageErr, setPageErr] = React.useState<string | null>(null);

  // Templates — fetched once on mount. The backend list is static enough
  // that we don't poll. Errors here are non-fatal (we just hide the
  // gallery and surface to the page banner).
  const [templates, setTemplates] = React.useState<AgentTemplate[] | null>(null);
  const [templateBusy, setTemplateBusy] = React.useState<string | null>(null);
  React.useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const list = await agentsApi.listTemplates(tok);
        if (mounted) setTemplates(list);
      } catch (e) {
        // 404 during a backend deploy or pre-shipped state — treat as
        // "no templates yet" rather than a hard error.
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
          if (mounted) setTemplates([]);
          return;
        }
        if (mounted) setPageErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { mounted = false; };
  }, [tok]);

  // Name-picker modal state for "create from template"
  const [pickFor, setPickFor] = React.useState<AgentTemplate | null>(null);
  const [pickName, setPickName] = React.useState("");

  function openTemplatePicker(t: AgentTemplate) {
    setPickFor(t);
    setPickName(t.name);
    setPageErr(null);
  }

  async function createFromTemplate() {
    if (!pickFor) return;
    const name = pickName.trim() || pickFor.name;
    setTemplateBusy(pickFor.key); setPageErr(null);
    try {
      const created = await agentsApi.createFromTemplate(tok, pickFor.key, { name });
      rememberAgent(created.id);
      await refresh();
      setPickFor(null);
      router.push(`/chat/${created.id}`);
    } catch (e) {
      setPageErr(e instanceof Error ? e.message : String(e));
    } finally {
      setTemplateBusy(null);
    }
  }

  async function create() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true); setPageErr(null);
    try {
      await agentsApi.create(tok, { name });
      await refresh();
      setNewName("");
      setCreating(false);
    } catch (e) {
      setPageErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true); setPageErr(null);
    try {
      await agentsApi.remove(tok, id);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setPageErr("Can't archive — this is your only active agent. Create another first.");
      } else {
        setPageErr(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  const active = agents.filter((a) => a.status === "active");
  const hibernated = agents.filter((a) => a.status === "hibernated");
  const archived = agents.filter((a) => a.status === "archived");
  const shownError = pageErr ?? error;

  return (
    <AppShell>
      <SectionHeader
        kicker="/00 · agents"
        title={<>One brief becomes <em style={{ fontStyle: "italic", fontWeight: 500 }}>one tireless coworker.</em></>}
        lede="Each agent is its own profile — its own memory, its own connections. Spin up as many as your team needs."
        right={
          <button onClick={() => setCreating(true)} style={primaryBtn}>
            + New agent
          </button>
        }
      />

      {shownError && <ErrorBanner>{shownError}</ErrorBanner>}

      {creating && (
        <div style={{ padding: "24px 56px", borderBottom: `1px solid ${theme.hair}`, background: theme.bgSoft }}>
          <Label>Name your agent</Label>
          <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") setCreating(false); }}
              placeholder="Aki Sales"
              style={inputStyle}
            />
            <button onClick={create} disabled={busy || !newName.trim()} style={primaryBtn}>
              {busy ? "…" : "Create"}
            </button>
            <button onClick={() => { setCreating(false); setNewName(""); }} style={secondaryBtn}>
              Cancel
            </button>
          </div>
          <div style={{
            marginTop: 8, fontFamily: theme.mono, fontSize: 10,
            color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase",
          }}>
            you can edit the brief after creation · or use /onboarding for a guided setup
          </div>
        </div>
      )}

      {templates && templates.length > 0 && (
        <section style={{ padding: "32px 56px 0" }}>
          <div style={{
            fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
            letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 14,
          }}>start from a template</div>
          <div className="aki-template-grid" style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 14,
          }}>
            {templates.map((t) => (
              <TemplateCard key={t.key} template={t}
                busy={templateBusy === t.key}
                onPick={() => openTemplatePicker(t)}/>
            ))}
          </div>
        </section>
      )}

      <section style={{ padding: "32px 56px 64px" }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 14,
        }}>your agents</div>
        {status === "loading" ? (
          <SkeletonList/>
        ) : agents.length === 0 ? (
          <Empty>No agents yet. <Link href="/onboarding" style={{ color: theme.accent, textDecoration: "none" }}>Start with onboarding →</Link></Empty>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            <Group label={`active · ${active.length}`}>
              {active.map((a) => <AgentRow key={a.id} agent={a} onDelete={() => remove(a.id)} canDelete={active.length > 1}/>)}
            </Group>
            {hibernated.length > 0 && (
              <Group label={`hibernated · ${hibernated.length}`}>
                {hibernated.map((a) => <AgentRow key={a.id} agent={a} onDelete={() => remove(a.id)} canDelete/>)}
              </Group>
            )}
            {archived.length > 0 && (
              <Group label={`archived · ${archived.length}`}>
                {archived.map((a) => <AgentRow key={a.id} agent={a}/>)}
              </Group>
            )}
          </div>
        )}
      </section>

      {pickFor && (
        <TemplateModal
          template={pickFor}
          name={pickName}
          onNameChange={setPickName}
          busy={templateBusy === pickFor.key}
          onCancel={() => setPickFor(null)}
          onConfirm={createFromTemplate}
        />
      )}
    </AppShell>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em",
        textTransform: "uppercase", color: theme.inkFaint, marginBottom: 14,
      }}>{label}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {children}
      </div>
    </div>
  );
}

function AgentRow({ agent, onDelete, canDelete }: {
  agent: import("@/lib/api").Agent;
  onDelete?: () => void;
  canDelete?: boolean;
}) {
  const lastActive = agent.hibernated_at
    ? `hibernated ${new Date(agent.hibernated_at).toLocaleDateString()}`
    : `created ${new Date(agent.created_at).toLocaleDateString()}`;
  return (
    <div style={{
      padding: "18px 22px", background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      display: "grid", gridTemplateColumns: "1fr auto auto", gap: 18, alignItems: "center",
    }}>
      <div style={{ minWidth: 0 }}>
        <Link href={`/agents/${agent.id}`} style={{
          fontFamily: theme.display, fontWeight: 600, fontSize: 22,
          letterSpacing: "-0.015em", color: theme.ink, textDecoration: "none",
        }}>{agent.name}</Link>
        <div style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.12em", marginTop: 4,
        }}>
          {agent.slug} · {lastActive}
        </div>
      </div>
      <Link href={`/chat/${agent.id}`} style={{
        fontFamily: theme.body, fontSize: 13, fontWeight: 500,
        color: theme.inkDim, textDecoration: "none",
        padding: "8px 16px", border: `1px solid ${theme.hair}`,
        borderRadius: 999,
      }}>Chat</Link>
      {onDelete && canDelete && agent.status === "active" && (
        <button onClick={onDelete} style={dangerBtn}>Archive</button>
      )}
      {onDelete && !canDelete && agent.status === "active" && (
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>last active</span>
      )}
    </div>
  );
}

function SkeletonList() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{
          padding: "18px 22px", background: theme.bgSoft,
          border: `1px solid ${theme.hair}`, height: 64,
        }}>
          <div style={{ height: 22, width: "30%", background: "rgba(241,237,224,0.06)", marginBottom: 8 }}/>
          <div style={{ height: 11, width: "20%", background: "rgba(241,237,224,0.04)" }}/>
        </div>
      ))}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "28px 30px", background: theme.bgSoft,
      border: `1px dashed ${theme.hair}`,
      fontFamily: theme.display, fontStyle: "italic", fontWeight: 500,
      fontSize: 18, color: theme.inkDim, letterSpacing: "-0.01em",
    }}>{children}</div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.22em", textTransform: "uppercase",
    }}>{children}</div>
  );
}

const inputStyle: React.CSSProperties = {
  flex: 1, background: theme.bg, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "10px 14px", fontFamily: theme.body, fontSize: 15,
  outline: "none",
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
};

const dangerBtn: React.CSSProperties = {
  background: "transparent", color: "#ee5959",
  border: "1px solid rgba(238,89,89,0.32)",
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "8px 16px", borderRadius: 999, cursor: "pointer",
};

function TemplateCard({ template, busy, onPick }: {
  template: AgentTemplate; busy: boolean; onPick: () => void;
}) {
  return (
    <button
      onClick={onPick}
      disabled={busy}
      style={{
        textAlign: "left", padding: "22px 22px",
        background: theme.bgSoft, border: `1px solid ${theme.hair}`,
        borderRadius: 6, cursor: busy ? "default" : "pointer",
        display: "flex", flexDirection: "column", gap: 12,
        opacity: busy ? 0.55 : 1,
        transition: "border-color 0.15s ease, transform 0.15s ease",
      }}
      onMouseEnter={(e) => {
        if (busy) return;
        e.currentTarget.style.borderColor = theme.accent;
      }}
      onMouseLeave={(e) => {
        if (busy) return;
        e.currentTarget.style.borderColor = theme.hair;
      }}
    >
      <div style={{
        fontFamily: theme.display, fontWeight: 600, fontSize: 22,
        letterSpacing: "-0.015em", color: theme.ink, lineHeight: 1.15,
      }}>{template.name}</div>
      <div style={{
        fontFamily: theme.body, fontSize: 13, color: theme.inkLede,
        lineHeight: 1.5, flex: 1,
      }}>{template.blurb}</div>
      {template.suggested_tools.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {template.suggested_tools.map((tool) => (
            <span key={tool} style={{
              fontFamily: theme.mono, fontSize: 10,
              padding: "3px 8px", borderRadius: 999,
              background: "rgba(241,237,224,0.05)",
              border: `1px solid ${theme.hair}`,
              color: theme.inkDim, letterSpacing: "0.06em",
            }}>{tool.replace(/_/g, " ")}</span>
          ))}
        </div>
      )}
      <div style={{
        marginTop: 4, fontFamily: theme.mono, fontSize: 10,
        color: busy ? theme.inkFaint : theme.accent,
        letterSpacing: "0.18em", textTransform: "uppercase",
      }}>
        {busy ? "creating…" : "use this template →"}
      </div>
    </button>
  );
}

function TemplateModal({ template, name, onNameChange, busy, onCancel, onConfirm }: {
  template: AgentTemplate;
  name: string;
  onNameChange: (next: string) => void;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(15,16,20,0.72)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div style={{
        background: theme.bg, border: `1px solid ${theme.hair}`,
        padding: "28px 32px", maxWidth: 480, width: "100%",
        boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
      }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.accent,
          letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 8,
        }}>{template.key} · template</div>
        <h2 style={{
          margin: 0, fontFamily: theme.display, fontWeight: 600,
          fontSize: 26, letterSpacing: "-0.015em", color: theme.ink,
        }}>Name your agent</h2>
        <p style={{
          marginTop: 8, marginBottom: 20, fontFamily: theme.body, fontSize: 14,
          color: theme.inkDim, lineHeight: 1.5,
        }}>
          You&rsquo;ll start with the {template.name} brief — edit it any time from the agent detail page.
        </p>

        <Label>name</Label>
        <input
          autoFocus
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy && name.trim()) onConfirm();
            if (e.key === "Escape" && !busy) onCancel();
          }}
          disabled={busy}
          style={{ ...inputStyle, marginTop: 8, width: "100%", boxSizing: "border-box" }}
        />

        <div style={{
          marginTop: 24, display: "flex", gap: 10, justifyContent: "flex-end",
        }}>
          <button onClick={onCancel} disabled={busy} style={secondaryBtn}>
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy || !name.trim()}
            style={{ ...primaryBtn, opacity: busy || !name.trim() ? 0.5 : 1 }}
          >
            {busy ? "Creating…" : "Create agent"}
          </button>
        </div>
      </div>
    </div>
  );
}
