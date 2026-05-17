"use client";

import * as React from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { connectionsApi, Connection } from "@/lib/api";

const ORG_SCOPE = "__org__";
const ARCADE_PENDING_KEY = "aki.arcade.pending";

type NativeProvider = "gmail" | "slack" | "notion" | "linear" | "hubspot";

type CatalogItem =
  | {
      kind: "native";
      provider: NativeProvider;
      name: string;
      blurb: string;
      glyph: React.ReactNode;
    }
  | {
      kind: "browser";
      provider: "browser";
      name: string;
      blurb: string;
      glyph: React.ReactNode;
    }
  | {
      kind: "arcade";
      /** Arcade auth-provider id (dashboard slug). Also used as the
       *  Connection.provider value the backend stores. */
      provider: string;
      name: string;
      blurb: string;
      glyph: React.ReactNode;
      scopes?: string[];
    };

type ArcadePending = {
  authId: string;
  provider: string;
  agentId: string | null;
  startedAt: number;
};

export default function ConnectPage() {
  return (
    <React.Suspense fallback={null}>
      <ConnectPageInner />
    </React.Suspense>
  );
}

function ConnectPageInner() {
  const search = useSearchParams();
  const router = useRouter();
  const tok = useAuthToken();
  const { agents } = useAgents();
  const urlAgent = search?.get("agent_id") ?? null;
  const [scope, setScope] = React.useState<string>(urlAgent ?? ORG_SCOPE);
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
      const list = await connectionsApi.list(tok, scope === ORG_SCOPE ? undefined : scope);
      setConns(list);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [tok, scope]);

  React.useEffect(() => {
    fetchConns();
  }, [fetchConns]);

  // Arcade redirect resolution. Arcade's hosted flow lands us back at
  // /connect?arcade=ok. We pull the pending auth_id from sessionStorage,
  // poll status once, then record. The backend re-fetches status server-side
  // so we don't need to trust anything but the auth_id we set ourselves.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    if (search?.get("arcade") !== "ok") return;
    const raw = sessionStorage.getItem(ARCADE_PENDING_KEY);
    if (!raw) return;
    let pending: ArcadePending;
    try {
      pending = JSON.parse(raw) as ArcadePending;
    } catch {
      sessionStorage.removeItem(ARCADE_PENDING_KEY);
      return;
    }
    sessionStorage.removeItem(ARCADE_PENDING_KEY);
    (async () => {
      setBusy(pending.provider);
      try {
        // One short-poll in case Arcade is still finalizing.
        const s = await connectionsApi.arcadeStatus(tok, pending.authId, 10);
        if (s.status !== "completed") {
          throw new Error(`Arcade auth ${s.status ?? "incomplete"}`);
        }
        await connectionsApi.arcadeRecord(tok, {
          auth_id: pending.authId,
          agent_id: pending.agentId,
        });
        setOk(true);
        await fetchConns();
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
        const params = new URLSearchParams(search?.toString() ?? "");
        params.delete("arcade");
        const qs = params.toString();
        router.replace(`/connect${qs ? `?${qs}` : ""}`);
      }
    })();
    // Run-once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    setBusy(item.provider);
    setErr(null);
    const agentArg = attachTo === ORG_SCOPE ? undefined : attachTo;
    try {
      if (item.kind === "browser") {
        await connectionsApi.browserEnable(tok, agentArg);
        await fetchConns();
        setBusy(null);
        return;
      }
      if (item.kind === "native") {
        const resp = await connectionsApi.oauthStart(tok, item.provider, agentArg);
        // The provider's redirect_uri points back to /connect/oauth/callback;
        // that page POSTs code+state to /connections/oauth/callback and
        // sends the user back here. No sessionStorage needed — state is
        // signed server-side.
        window.location.href = resp.auth_url;
        return;
      }
      if (item.kind === "arcade") {
        const resp = await connectionsApi.arcadeStart(tok, {
          provider: item.provider,
          agent_id: agentArg ?? null,
          scopes: item.scopes,
        });
        const pending: ArcadePending = {
          authId: resp.auth_id,
          provider: item.provider,
          agentId: agentArg ?? null,
          startedAt: Date.now(),
        };
        sessionStorage.setItem(ARCADE_PENDING_KEY, JSON.stringify(pending));
        if (!resp.auth_url) {
          // Already authorized server-side — short-circuit straight to record.
          try {
            await connectionsApi.arcadeRecord(tok, {
              auth_id: resp.auth_id,
              agent_id: agentArg ?? null,
            });
            sessionStorage.removeItem(ARCADE_PENDING_KEY);
            setOk(true);
            await fetchConns();
          } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
          } finally {
            setBusy(null);
          }
          return;
        }
        window.location.href = resp.auth_url;
        return;
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

  const active = (conns ?? []).filter((c) => c.status === "active");
  const orgWide = active.filter((c) => c.agent_id === null);
  const perAgent = active.filter((c) => c.agent_id !== null);

  function alreadyConnected(provider: string): boolean {
    if (attachTo === ORG_SCOPE) return orgWide.some((c) => c.provider === provider);
    return active.some(
      (c) => c.provider === provider && (c.agent_id === null || c.agent_id === attachTo),
    );
  }

  const scopedAgentName =
    scope === ORG_SCOPE
      ? "All agents (org-wide)"
      : agents.find((a) => a.id === scope)?.name ?? "…";

  return (
    <AppShell>
      <SectionHeader
        kicker="/01 · connections"
        title={
          <>
            Connect a tool. <em style={{ fontStyle: "italic", fontWeight: 500 }}>The agent does the rest.</em>
          </>
        }
        lede="Top tools use our own OAuth — your tokens land directly in our vault, no middleman. Long-tail apps route through Arcade. We never see your password."
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {ok && !err && (
        <div
          style={{
            margin: "16px 56px",
            padding: "10px 18px",
            background: "rgba(197,236,79,0.08)",
            border: `1px solid ${theme.accentDim}`,
            color: theme.accent,
            fontFamily: theme.mono,
            fontSize: 12,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>connected · ready to use</span>
          <button
            onClick={() => setOk(false)}
            style={{
              background: "transparent",
              border: "none",
              color: theme.inkDim,
              fontFamily: theme.mono,
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <section style={{ padding: "32px 56px 0" }}>
        <Kicker>viewing</Kicker>
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            flexWrap: "wrap",
            padding: "14px 18px",
            background: theme.bgSoft,
            border: `1px solid ${theme.hair}`,
          }}
        >
          <span style={{ fontFamily: theme.body, fontSize: 13, color: theme.inkDim }}>
            Show connections for
          </span>
          <select
            value={scope}
            onChange={(e) => setScopeAndPushUrl(e.target.value)}
            style={selectStyle}
          >
            <option value={ORG_SCOPE}>All agents (org-wide)</option>
            {agents
              .filter((a) => a.status === "active")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  Only for {a.name}
                </option>
              ))}
          </select>
          <span style={{ flex: 1 }} />
          <span
            style={{
              fontFamily: theme.mono,
              fontSize: 10,
              color: theme.inkFaint,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
            }}
          >
            new connections attach to: {scopedAgentName}
          </span>
        </div>
      </section>

      <section style={{ padding: "32px 56px 0" }}>
        <Kicker>active · {active.length}</Kicker>
        {conns === null ? (
          <CardGrid>
            {[0, 1, 2].map((i) => (
              <SkeletonCard key={i} />
            ))}
          </CardGrid>
        ) : active.length === 0 ? (
          <EmptyState>Nothing yet for this scope. Pick a tool below.</EmptyState>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            {orgWide.length > 0 && (
              <ConnGroup label={`shared with all agents · ${orgWide.length}`}>
                {orgWide.map((c) => (
                  <ActiveCard
                    key={c.id}
                    conn={c}
                    agentName={null}
                    onDisable={c.provider === "browser" ? () => disable(c) : undefined}
                    busy={busy === c.id}
                  />
                ))}
              </ConnGroup>
            )}
            {perAgent.length > 0 && (
              <ConnGroup label={`per-agent · ${perAgent.length}`}>
                {perAgent.map((c) => (
                  <ActiveCard
                    key={c.id}
                    conn={c}
                    agentName={agents.find((a) => a.id === c.agent_id)?.name ?? "(unknown agent)"}
                    onDisable={c.provider === "browser" ? () => disable(c) : undefined}
                    busy={busy === c.id}
                  />
                ))}
              </ConnGroup>
            )}
          </div>
        )}
      </section>

      <section style={{ padding: "32px 56px 0" }}>
        <Kicker>native · our own oauth</Kicker>
        <CardGrid>
          {NATIVE_CATALOG.map((item) => {
            const already = alreadyConnected(item.provider);
            return (
              <CatalogCardEl
                key={item.provider}
                item={item}
                already={already}
                attachToName={scopedAgentName}
                busy={busy === item.provider}
                onConnect={() => connect(item)}
              />
            );
          })}
          <CatalogCardEl
            key={BROWSER_ITEM.provider}
            item={BROWSER_ITEM}
            already={alreadyConnected(BROWSER_ITEM.provider)}
            attachToName={scopedAgentName}
            busy={busy === BROWSER_ITEM.provider}
            onConnect={() => connect(BROWSER_ITEM)}
          />
        </CardGrid>
      </section>

      <section style={{ padding: "32px 56px 64px" }}>
        <Kicker>other · via arcade</Kicker>
        <div
          style={{
            fontFamily: theme.body,
            fontSize: 13,
            color: theme.inkDim,
            marginTop: -10,
            marginBottom: 18,
            maxWidth: 640,
            lineHeight: 1.55,
          }}
        >
          Long-tail SaaS we route through Arcade&apos;s managed OAuth gateway. Same
          per-org / per-agent scoping, same encrypted storage — just a different
          token issuer on the back end.
        </div>
        <CardGrid>
          {ARCADE_CATALOG.map((item) => {
            const already = alreadyConnected(item.provider);
            return (
              <CatalogCardEl
                key={item.provider}
                item={item}
                already={already}
                attachToName={scopedAgentName}
                busy={busy === item.provider}
                onConnect={() => connect(item)}
              />
            );
          })}
        </CardGrid>
      </section>
    </AppShell>
  );
}

// ─── catalogs ──────────────────────────────────────────────────────────

const NATIVE_CATALOG: CatalogItem[] = [
  {
    kind: "native",
    provider: "gmail",
    name: "Gmail",
    blurb: "Read, draft, send, label, and search.",
    glyph: <ProviderGlyph color="#ea4335">M</ProviderGlyph>,
  },
  {
    kind: "native",
    provider: "slack",
    name: "Slack",
    blurb: "Post messages, list channels, read threads.",
    glyph: <ProviderGlyph color="#611f69">S</ProviderGlyph>,
  },
  {
    kind: "native",
    provider: "notion",
    name: "Notion",
    blurb: "Read pages, create entries in selected databases.",
    glyph: <ProviderGlyph color="#e3dcc5">N</ProviderGlyph>,
  },
  {
    kind: "native",
    provider: "linear",
    name: "Linear",
    blurb: "Read, comment, and transition issues across teams.",
    glyph: <ProviderGlyph color="#5e6ad2">L</ProviderGlyph>,
  },
  {
    kind: "native",
    provider: "hubspot",
    name: "HubSpot",
    blurb: "Read and create contacts, log activity, manage deals.",
    glyph: <ProviderGlyph color="#ff7a59">H</ProviderGlyph>,
  },
];

const BROWSER_ITEM: CatalogItem = {
  kind: "browser",
  provider: "browser",
  name: "Browser Mode",
  blurb: "For any tool without an API — Aki drives a real Chrome via Browser Use.",
  glyph: <ProviderGlyph color={theme.accent}>↗</ProviderGlyph>,
};

// Long-tail providers we route through Arcade. The `provider` string is the
// Arcade dashboard auth-provider id and becomes Connection.provider on the
// backend (see /connections/arcade/record). Add new entries here once you
// register them in the Arcade admin.
const ARCADE_CATALOG: CatalogItem[] = [
  {
    kind: "arcade",
    provider: "google_calendar",
    name: "Google Calendar",
    blurb: "Read availability, create and update events.",
    glyph: <ProviderGlyph color="#4285f4">C</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "google_drive",
    name: "Google Drive",
    blurb: "Search files, fetch contents, upload generated docs.",
    glyph: <ProviderGlyph color="#0f9d58">D</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "github",
    name: "GitHub",
    blurb: "Read repos, comment on PRs and issues, manage labels.",
    glyph: <ProviderGlyph color="#e3dcc5">G</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "asana",
    name: "Asana",
    blurb: "Read and update tasks, post comments across projects.",
    glyph: <ProviderGlyph color="#f06a6a">A</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "jira",
    name: "Jira",
    blurb: "Search issues, comment, transition status.",
    glyph: <ProviderGlyph color="#2684ff">J</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "zoom",
    name: "Zoom",
    blurb: "Schedule meetings, fetch recordings and transcripts.",
    glyph: <ProviderGlyph color="#2d8cff">Z</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "dropbox",
    name: "Dropbox",
    blurb: "Search and fetch files; upload generated assets.",
    glyph: <ProviderGlyph color="#0061ff">B</ProviderGlyph>,
  },
  {
    kind: "arcade",
    provider: "microsoft",
    name: "Microsoft 365",
    blurb: "Outlook, Calendar, OneDrive — read, draft, send.",
    glyph: <ProviderGlyph color="#0078d4">O</ProviderGlyph>,
  },
];

// ─── presentational helpers ────────────────────────────────────────────

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: theme.mono,
        fontSize: 11,
        letterSpacing: "0.22em",
        textTransform: "uppercase",
        color: theme.inkFaint,
        marginBottom: 20,
      }}
    >
      {children}
    </div>
  );
}

function ConnGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 10,
          color: theme.inkFaint,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          marginBottom: 12,
        }}
      >
        {label}
      </div>
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
    <div
      style={{
        padding: "28px 30px",
        background: theme.bgSoft,
        border: `1px dashed ${theme.hair}`,
        fontFamily: theme.display,
        fontStyle: "italic",
        fontWeight: 500,
        fontSize: 18,
        color: theme.inkDim,
        letterSpacing: "-0.01em",
      }}
    >
      {children}
    </div>
  );
}

function ProviderGlyph({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div
      style={{
        width: 40,
        height: 40,
        borderRadius: 8,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: `${color}22`,
        border: `1px solid ${color}55`,
        fontFamily: theme.display,
        fontWeight: 700,
        fontSize: 22,
        color,
      }}
    >
      {children}
    </div>
  );
}

function ActiveCard({
  conn,
  agentName,
  onDisable,
  busy,
}: {
  conn: Connection;
  agentName: string | null;
  onDisable?: () => void;
  busy: boolean;
}) {
  return (
    <div style={{ padding: "20px 22px", background: theme.bgSoft, border: `1px solid ${theme.hair}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div
          style={{
            fontFamily: theme.display,
            fontWeight: 600,
            fontSize: 24,
            letterSpacing: "-0.015em",
            textTransform: "capitalize",
          }}
        >
          {conn.provider.replace(/_/g, " ")}
        </div>
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 10,
            color: theme.accent,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
          }}
        >
          ● active
        </span>
      </div>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 10,
          color: theme.inkLede,
          letterSpacing: "0.12em",
          marginBottom: 6,
        }}
      >
        {agentName ? `for ${agentName}` : "shared with all agents"}
      </div>
      {conn.external_account_id && (
        <div
          style={{
            fontFamily: theme.mono,
            fontSize: 10,
            color: theme.inkFaint,
            wordBreak: "break-all",
            marginBottom: 12,
          }}
        >
          {conn.external_account_id}
        </div>
      )}
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 10,
          color: theme.inkFaint,
          marginBottom: onDisable ? 14 : 0,
        }}
      >
        since {new Date(conn.created_at).toLocaleDateString()}
      </div>
      {onDisable && (
        <button
          onClick={onDisable}
          disabled={busy}
          style={{
            background: "transparent",
            color: theme.inkDim,
            border: `1px solid ${theme.hair}`,
            fontFamily: theme.body,
            fontSize: 12,
            fontWeight: 500,
            padding: "6px 14px",
            borderRadius: 999,
            cursor: busy ? "default" : "pointer",
            opacity: busy ? 0.5 : 1,
          }}
        >
          {busy ? "…" : "Disable"}
        </button>
      )}
    </div>
  );
}

function CatalogCardEl({
  item,
  already,
  busy,
  attachToName,
  onConnect,
}: {
  item: CatalogItem;
  already: boolean;
  busy: boolean;
  attachToName: string;
  onConnect: () => void;
}) {
  const buttonLabel = (() => {
    if (already) return "Connected";
    if (busy) {
      if (item.kind === "browser") return "Enabling…";
      if (item.kind === "arcade") return "Opening Arcade…";
      return "Redirecting…";
    }
    if (item.kind === "browser") return `Enable for ${attachToName}`;
    return `Connect ${item.name}`;
  })();

  return (
    <div
      style={{
        padding: "22px 24px",
        background: theme.bgSoft,
        border: `1px solid ${theme.hair}`,
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {item.glyph}
        <div
          style={{
            fontFamily: theme.display,
            fontWeight: 600,
            fontSize: 26,
            letterSpacing: "-0.015em",
          }}
        >
          {item.name}
        </div>
      </div>
      <div
        style={{
          fontFamily: theme.body,
          fontSize: 14,
          color: theme.inkLede,
          lineHeight: 1.5,
          flex: 1,
        }}
      >
        {item.blurb}
      </div>
      <button
        onClick={onConnect}
        disabled={busy || already}
        style={{
          background: already ? "transparent" : theme.accent,
          color: already ? theme.inkFaint : theme.bg,
          border: already ? `1px solid ${theme.hair}` : "none",
          fontFamily: theme.body,
          fontWeight: 600,
          fontSize: 13,
          padding: "10px 18px",
          borderRadius: 999,
          cursor: already || busy ? "default" : "pointer",
          opacity: busy ? 0.5 : 1,
          alignSelf: "flex-start",
        }}
      >
        {buttonLabel}
      </button>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div style={{ padding: "22px 24px", background: theme.bgSoft, border: `1px solid ${theme.hair}`, height: 142 }}>
      <div style={{ height: 26, width: "60%", background: "rgba(241,237,224,0.06)", marginBottom: 14 }} />
      <div style={{ height: 12, width: "85%", background: "rgba(241,237,224,0.04)", marginBottom: 8 }} />
      <div style={{ height: 12, width: "70%", background: "rgba(241,237,224,0.04)" }} />
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  background: theme.bg,
  color: theme.ink,
  border: `1px solid ${theme.hair}`,
  borderRadius: 6,
  padding: "8px 12px",
  fontFamily: theme.body,
  fontSize: 13,
  outline: "none",
  cursor: "pointer",
};
