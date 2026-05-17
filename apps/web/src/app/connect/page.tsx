"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";

type Connection = {
  id: string;
  provider: string;
  status: string;
  scopes: string[];
  external_account_id: string | null;
  created_at: string;
};

type CatalogItem = {
  provider: string;
  name: string;
  blurb: string;
  kind: "oauth" | "browser";
  glyph: React.ReactNode;
};

export default function ConnectPage() {
  const { getToken } = useAuth();
  const [conns, setConns] = React.useState<Connection[] | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  const fetchConns = React.useCallback(async () => {
    setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/connections`, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`GET /connections ${r.status}`);
      setConns(await r.json());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [getToken]);

  React.useEffect(() => { fetchConns(); }, [fetchConns]);

  async function connect(item: CatalogItem) {
    setBusy(item.provider); setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const headers = { Authorization: `Bearer ${token}` };
      if (item.kind === "oauth") {
        const r = await fetch(`${API_URL}/connections/oauth/start?provider=${item.provider}`, { method: "POST", headers });
        if (!r.ok) throw new Error(`oauth/start ${r.status}: ${await r.text()}`);
        const { url } = await r.json();
        window.location.href = url;
      } else if (item.kind === "browser") {
        const r = await fetch(`${API_URL}/connections/browser/enable`, { method: "POST", headers });
        if (!r.ok) throw new Error(`browser/enable ${r.status}: ${await r.text()}`);
        await fetchConns();
        setBusy(null);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  async function disable(prov: string) {
    setBusy(prov);
    try {
      const token = await getToken({ template: "aki" });
      const headers = { Authorization: `Bearer ${token}` };
      if (prov === "browser") {
        await fetch(`${API_URL}/connections/browser/disable`, { method: "POST", headers });
      }
      await fetchConns();
    } finally {
      setBusy(null);
    }
  }

  const catalog: CatalogItem[] = [
    { provider: "gmail", name: "Gmail", kind: "oauth",
      blurb: "Read, draft, send, label, and search your inbox.",
      glyph: <ProviderGlyph color="#ea4335">M</ProviderGlyph> },
    { provider: "slack", name: "Slack", kind: "oauth",
      blurb: "Post in channels, DM teammates, and read messages.",
      glyph: <ProviderGlyph color="#611f69">S</ProviderGlyph> },
    { provider: "browser", name: "Browser Mode", kind: "browser",
      blurb: "For any tool without an API — Aki drives a real Chrome via Browser Use.",
      glyph: <ProviderGlyph color={theme.accent}>↗</ProviderGlyph> },
  ];

  const active = conns?.filter((c) => c.status === "active") ?? [];

  return (
    <AppShell>
      <SectionHeader
        kicker="/01 · connections"
        title={<>Connect a tool. <em style={{ fontStyle: "italic", fontWeight: 500 }}>The agent does the rest.</em></>}
        lede="Each connection gives Aki scoped access via Composio. OAuth happens on the provider&rsquo;s domain; we never see your password."
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      <section style={{ padding: "40px 56px" }}>
        <Kicker>active · {active.length}</Kicker>
        {conns === null ? (
          <CardGrid>{[0,1,2].map((i) => <SkeletonCard key={i}/>)}</CardGrid>
        ) : active.length === 0 ? (
          <EmptyState>No connections yet. Pick one below to give Aki access.</EmptyState>
        ) : (
          <CardGrid>
            {active.map((c) => (
              <ActiveCard key={c.id} conn={c}
                onDisable={c.provider === "browser" ? () => disable(c.provider) : undefined}
                busy={busy === c.provider}/>
            ))}
          </CardGrid>
        )}
      </section>

      <section style={{ padding: "0 56px 64px" }}>
        <Kicker>available</Kicker>
        <CardGrid>
          {catalog.map((item) => {
            const already = active.some((c) => c.provider === item.provider);
            return (
              <CatalogCardEl key={item.provider} item={item} already={already}
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
    <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 20 }}>
      {children}
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
    <div style={{ padding: "28px 30px", background: theme.bgSoft, border: `1px dashed ${theme.hair}`, fontFamily: theme.display, fontStyle: "italic", fontWeight: 500, fontSize: 18, color: theme.inkDim, letterSpacing: "-0.01em" }}>
      {children}
    </div>
  );
}

function ProviderGlyph({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div style={{
      width: 40, height: 40, borderRadius: 8,
      display: "flex", alignItems: "center", justifyContent: "center",
      background: `${color}22`, border: `1px solid ${color}55`,
      fontFamily: theme.display, fontWeight: 700, fontSize: 22, color,
    }}>
      {children}
    </div>
  );
}

function ActiveCard({ conn, onDisable, busy }: { conn: Connection; onDisable?: () => void; busy: boolean }) {
  return (
    <div style={{ padding: "20px 22px", background: theme.bgSoft, border: `1px solid ${theme.hair}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 24, letterSpacing: "-0.015em", textTransform: "capitalize" }}>
          {conn.provider}
        </div>
        <span style={{ fontFamily: theme.mono, fontSize: 10, color: theme.accent, letterSpacing: "0.18em", textTransform: "uppercase" }}>
          ● active
        </span>
      </div>
      {conn.external_account_id && (
        <div style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, wordBreak: "break-all", marginBottom: 12 }}>
          {conn.external_account_id}
        </div>
      )}
      <div style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, marginBottom: onDisable ? 14 : 0 }}>
        since {new Date(conn.created_at).toLocaleDateString()}
      </div>
      {onDisable && (
        <button onClick={onDisable} disabled={busy} style={{
          background: "transparent", color: theme.inkDim,
          border: `1px solid ${theme.hair}`,
          fontFamily: theme.body, fontSize: 12, fontWeight: 500,
          padding: "6px 14px", borderRadius: 999, cursor: busy ? "default" : "pointer",
          opacity: busy ? 0.5 : 1,
        }}>{busy ? "…" : "Disable"}</button>
      )}
    </div>
  );
}

function CatalogCardEl({ item, already, busy, onConnect }: { item: CatalogItem; already: boolean; busy: boolean; onConnect: () => void }) {
  return (
    <div style={{ padding: "22px 24px", background: theme.bgSoft, border: `1px solid ${theme.hair}`, display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {item.glyph}
        <div style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 26, letterSpacing: "-0.015em" }}>
          {item.name}
        </div>
      </div>
      <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkLede, lineHeight: 1.5, flex: 1 }}>
        {item.blurb}
      </div>
      <button onClick={onConnect} disabled={busy || already} style={{
        background: already ? "transparent" : theme.accent,
        color: already ? theme.inkFaint : theme.bg,
        border: already ? `1px solid ${theme.hair}` : "none",
        fontFamily: theme.body, fontWeight: 600, fontSize: 13,
        padding: "10px 18px", borderRadius: 999,
        cursor: already || busy ? "default" : "pointer",
        opacity: busy ? 0.5 : 1, alignSelf: "flex-start",
      }}>
        {already ? "Connected" : busy ? (item.kind === "oauth" ? "Redirecting…" : "Enabling…") : item.kind === "browser" ? `Enable ${item.name}` : `Connect ${item.name}`}
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
