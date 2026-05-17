"use client";

import * as React from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { connectionsApi, Connection } from "@/lib/api";

const ORG_SCOPE = "__org__";

type CatalogItem = {
  provider: string;
  name: string;
  blurb: string;
  kind: "oauth" | "browser";
  glyph: React.ReactNode;
};

export default function ConnectPage() {
  return (
    <React.Suspense fallback={null}>
      <ConnectPageInner/>
    </React.Suspense>
  );
}

function ConnectPageInner() {
  const search = useSearchParams();
  const router = useRouter();
  const tok = useAuthToken();
  const { agents } = useAgents();
  const urlAgent = search?.get("agent_id") ?? null;
  // scope: ORG_SCOPE means "org-wide only", agent id means "viewing this agent"
  const [scope, setScope] = React.useState<string>(urlAgent ?? ORG_SCOPE);
  // Where new connections should be attached when user clicks "Connect"
  const [attachTo, setAttachTo] = React.useState<string>(urlAgent ?? ORG_SCOPE);

  React.useEffect(() => {
    if (urlAgent && agents.some((a) => a.id === urlAgent)) {
      setScope(urlAgent);
      setAttachTo(urlAgent);
    }
  }, [urlAgent, agents]);

  const [conns, setConns] = React.useState<Connection[] | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(search?.get("err") || null);
  const [ok, setOk] = React.useState<boolean>(search?.get("ok") === "1");

  const fetchConns = React.useCallback(async () => {
    setErr(null);
    try {
      // When viewing a specific agent, fetch with agent_id so we get
      // org-wide ∪ that agent's connections. When viewing org-wide,
      // omit agent_id; we'll filter to agent_id IS NULL client-side.
      const list = await connectionsApi.list(tok, scope === ORG_SCOPE ? undefined : scope);
      setConns(list);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [tok, scope]);

  React.useEffect(() => { fetchConns(); }, [fetchConns]);

  function setScopeAndPushUrl(next: string) {
    setScope(next);
    setAttachTo(next);
    const params = new URLSearchParams(search?.toString() ?? "");
    if (next === ORG_SCOPE) params.delete("agent_id");
    else params.set("agent_id", next);
    const qs = params.toString();
    router.replace(`/connect${qs ? `?${qs}` : ""}`);
  }

  async function connect(item: CatalogItem) {
    setBusy(item.provider); setErr(null);
    try {
      const agentArg = attachTo === ORG_SCOPE ? undefined : attachTo;
      if (item.kind === "oauth") {
        const { url } = await connectionsApi.oauthStart(tok, item.provider, agentArg);
        window.location.href = url;
        return;
      }
      if (item.kind === "browser") {
        await connectionsApi.browserEnable(tok, agentArg);
        await fetchConns();
        setBusy(null);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  async function disable(conn: Connection) {
    setBusy(conn.id);
    try {
      if (conn.provider === "browser") {
        await connectionsApi.browserDisable(tok, conn.agent_id ?? undefined);
      }
      await fetchConns();
    } finally {
      setBusy(null);
    }
  }

  const catalog: CatalogItem[] = [
    { provider: "gmail", name: "Gmail", kind: "oauth",
      blurb: "Read, draft, send, label, and search.",
      glyph: <ProviderGlyph color="#ea4335">M</ProviderGlyph> },
    { provider: "slackbot", name: "Slack (as a bot)", kind: "oauth",
      blurb: "Installs Aki as a workspace bot — messages come from Aki, not from you.",
      glyph: <ProviderGlyph color="#611f69">S</ProviderGlyph> },
    { provider: "browser", name: "Browser Mode", kind: "browser",
      blurb: "For any tool without an API — Aki drives a real Chrome via Browser Use.",
      glyph: <ProviderGlyph color={theme.accent}>↗</ProviderGlyph> },
  ];

  const active = (conns ?? []).filter((c) => c.status === "active");
  const orgWide = active.filter((c) => c.agent_id === null);
  const perAgent = active.filter((c) => c.agent_id !== null);

  // For "already connected" badge: when attaching to a specific agent,
  // a connection counts if it's org-wide OR attached to this agent.
  // When attaching org-wide, only org-wide counts.
  function alreadyConnected(provider: string): boolean {
    if (attachTo === ORG_SCOPE) return orgWide.some((c) => c.provider === provider);
    return active.some((c) => c.provider === provider && (c.agent_id === null || c.agent_id === attachTo));
  }

  const scopedAgentName = scope === ORG_SCOPE
    ? "All agents (org-wide)"
    : agents.find((a) => a.id === scope)?.name ?? "…";

  return (
    <AppShell>
      <SectionHeader
        kicker="/01 · connections"
        title={<>Connect a tool. <em style={{ fontStyle: "italic", fontWeight: 500 }}>The agent does the rest.</em></>}
        lede="Each connection gives an agent scoped access via Composio. OAuth happens on the provider's domain; we never see your password."
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {ok && !err && (
        <div style={{
          margin: "16px 56px", padding: "10px 18px",
          background: "rgba(197,236,79,0.08)", border: `1px solid ${theme.accentDim}`,
          color: theme.accent, fontFamily: theme.mono, fontSize: 12,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span>connected · ready to use</span>
          <button onClick={() => setOk(false)} style={{
            background: "transparent", border: "none", color: theme.inkDim,
            fontFamily: theme.mono, fontSize: 12, cursor: "pointer",
          }}>dismiss</button>
        </div>
      )}

      <section style={{ padding: "32px 56px 0" }}>
        <Kicker>viewing</Kicker>
        <div style={{
          display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
          padding: "14px 18px", background: theme.bgSoft, border: `1px solid ${theme.hair}`,
        }}>
          <span style={{ fontFamily: theme.body, fontSize: 13, color: theme.inkDim }}>
            Show connections for
          </span>
          <select
            value={scope}
            onChange={(e) => setScopeAndPushUrl(e.target.value)}
            style={selectStyle}
          >
            <option value={ORG_SCOPE}>All agents (org-wide)</option>
            {agents.filter((a) => a.status === "active").map((a) => (
              <option key={a.id} value={a.id}>Only for {a.name}</option>
            ))}
          </select>
          <span style={{ flex: 1 }}/>
          <span style={{
            fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
            letterSpacing: "0.18em", textTransform: "uppercase",
          }}>
            new connections attach to: {scopedAgentName}
          </span>
        </div>
      </section>

      <section style={{ padding: "32px 56px 0" }}>
        <Kicker>active · {active.length}</Kicker>
        {conns === null ? (
          <CardGrid>{[0,1,2].map((i) => <SkeletonCard key={i}/>)}</CardGrid>
        ) : active.length === 0 ? (
          <EmptyState>Nothing yet for this scope. Pick a tool below.</EmptyState>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            {orgWide.length > 0 && (
              <ConnGroup label={`shared with all agents · ${orgWide.length}`}>
                {orgWide.map((c) => (
                  <ActiveCard key={c.id} conn={c} agentName={null}
                    onDisable={c.provider === "browser" ? () => disable(c) : undefined}
                    busy={busy === c.id}/>
                ))}
              </ConnGroup>
            )}
            {perAgent.length > 0 && (
              <ConnGroup label={`per-agent · ${perAgent.length}`}>
                {perAgent.map((c) => (
                  <ActiveCard key={c.id} conn={c}
                    agentName={agents.find((a) => a.id === c.agent_id)?.name ?? "(unknown agent)"}
                    onDisable={c.provider === "browser" ? () => disable(c) : undefined}
                    busy={busy === c.id}/>
                ))}
              </ConnGroup>
            )}
          </div>
        )}
      </section>

      <section style={{ padding: "32px 56px 64px" }}>
        <Kicker>available</Kicker>
        <CardGrid>
          {catalog.map((item) => {
            const already = alreadyConnected(item.provider);
            return (
              <CatalogCardEl key={item.provider} item={item} already={already}
                attachToName={scopedAgentName}
                busy={busy === item.provider}
                onConnect={() => connect(item)}/>
            );
          })}
        </CardGrid>
      </section>
    </AppShell>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em",
      textTransform: "uppercase", color: theme.inkFaint, marginBottom: 20,
    }}>{children}</div>
  );
}

function ConnGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
        letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 12,
      }}>{label}</div>
      <CardGrid>{children}</CardGrid>
    </div>
  );
}

function CardGrid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 18 }}>
      {children}
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "28px 30px", background: theme.bgSoft,
      border: `1px dashed ${theme.hair}`,
      fontFamily: theme.display, fontStyle: "italic", fontWeight: 500,
      fontSize: 18, color: theme.inkDim, letterSpacing: "-0.01em",
    }}>{children}</div>
  );
}

function ProviderGlyph({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div style={{
      width: 40, height: 40, borderRadius: 8,
      display: "flex", alignItems: "center", justifyContent: "center",
      background: `${color}22`, border: `1px solid ${color}55`,
      fontFamily: theme.display, fontWeight: 700, fontSize: 22, color,
    }}>{children}</div>
  );
}

function ActiveCard({ conn, agentName, onDisable, busy }: {
  conn: Connection; agentName: string | null; onDisable?: () => void; busy: boolean;
}) {
  return (
    <div style={{ padding: "20px 22px", background: theme.bgSoft, border: `1px solid ${theme.hair}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{
          fontFamily: theme.display, fontWeight: 600, fontSize: 24,
          letterSpacing: "-0.015em", textTransform: "capitalize",
        }}>{conn.provider}</div>
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.accent,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>● active</span>
      </div>
      <div style={{
        fontFamily: theme.mono, fontSize: 10, color: theme.inkLede,
        letterSpacing: "0.12em", marginBottom: 6,
      }}>
        {agentName ? `for ${agentName}` : "shared with all agents"}
      </div>
      {conn.external_account_id && (
        <div style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          wordBreak: "break-all", marginBottom: 12,
        }}>{conn.external_account_id}</div>
      )}
      <div style={{
        fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
        marginBottom: onDisable ? 14 : 0,
      }}>since {new Date(conn.created_at).toLocaleDateString()}</div>
      {onDisable && (
        <button onClick={onDisable} disabled={busy} style={{
          background: "transparent", color: theme.inkDim,
          border: `1px solid ${theme.hair}`,
          fontFamily: theme.body, fontSize: 12, fontWeight: 500,
          padding: "6px 14px", borderRadius: 999,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.5 : 1,
        }}>{busy ? "…" : "Disable"}</button>
      )}
    </div>
  );
}

function CatalogCardEl({ item, already, busy, attachToName, onConnect }: {
  item: CatalogItem; already: boolean; busy: boolean; attachToName: string; onConnect: () => void;
}) {
  return (
    <div style={{
      padding: "22px 24px", background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {item.glyph}
        <div style={{
          fontFamily: theme.display, fontWeight: 600, fontSize: 26, letterSpacing: "-0.015em",
        }}>{item.name}</div>
      </div>
      <div style={{
        fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
        lineHeight: 1.5, flex: 1,
      }}>{item.blurb}</div>
      <button onClick={onConnect} disabled={busy || already} style={{
        background: already ? "transparent" : theme.accent,
        color: already ? theme.inkFaint : theme.bg,
        border: already ? `1px solid ${theme.hair}` : "none",
        fontFamily: theme.body, fontWeight: 600, fontSize: 13,
        padding: "10px 18px", borderRadius: 999,
        cursor: already || busy ? "default" : "pointer",
        opacity: busy ? 0.5 : 1, alignSelf: "flex-start",
      }}>
        {already ? "Connected" : busy
          ? (item.kind === "oauth" ? "Redirecting…" : "Enabling…")
          : item.kind === "browser" ? `Enable for ${attachToName}` : `Connect ${item.name}`}
      </button>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div style={{ padding: "22px 24px", background: theme.bgSoft, border: `1px solid ${theme.hair}`, height: 142 }}>
      <div style={{ height: 26, width: "60%", background: "rgba(241,237,224,0.06)", marginBottom: 14 }}/>
      <div style={{ height: 12, width: "85%", background: "rgba(241,237,224,0.04)", marginBottom: 8 }}/>
      <div style={{ height: 12, width: "70%", background: "rgba(241,237,224,0.04)" }}/>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  background: theme.bg, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "8px 12px", fontFamily: theme.body, fontSize: 13,
  outline: "none", cursor: "pointer",
};
