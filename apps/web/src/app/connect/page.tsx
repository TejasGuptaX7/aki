"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton, useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";

type Connection = {
  id: string;
  provider: string;
  status: string;
  scopes: string[];
  external_account_id: string | null;
  created_at: string;
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
      const r = await fetch(`${API_URL}/connections`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`GET /connections ${r.status}`);
      setConns(await r.json());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [getToken]);

  React.useEffect(() => { fetchConns(); }, [fetchConns]);

  async function connect(provider: string) {
    setBusy(provider); setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/connections/oauth/start?provider=${provider}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`oauth/start ${r.status}: ${await r.text()}`);
      const { url } = await r.json();
      window.location.href = url;
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  const catalog: { provider: string; name: string; blurb: string }[] = [
    { provider: "gmail", name: "Gmail", blurb: "Read, draft, send, and search your inbox." },
  ];

  return (
    <div style={{
      minHeight: "100vh", background: theme.bg, color: theme.ink,
      fontFamily: theme.body, padding: "28px 56px",
    }}>
      {/* nav */}
      <nav style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 64 }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 14, textDecoration: "none", color: theme.ink }}>
          <span style={{ display: "inline-block", width: 28, height: 28, fontFamily: theme.display, fontWeight: 700, fontSize: 36, lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em" }}>a</span>
          <span style={{ fontFamily: theme.body, fontWeight: 600, fontSize: 16, letterSpacing: "0.04em" }}>aki</span>
          <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.12em" }}>v 0.7</span>
        </Link>
        <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
          <Link href="/chat" style={{ color: theme.inkDim, textDecoration: "none", fontSize: 14, fontWeight: 500 }}>Chat</Link>
          <Link href="/connect" style={{ color: theme.accent, textDecoration: "none", fontSize: 14, fontWeight: 500 }}>Connect</Link>
          <UserButton/>
        </div>
      </nav>

      {/* header */}
      <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 18 }}>
        /01 · connections
      </div>
      <div style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 60, lineHeight: 1.05, letterSpacing: "-0.025em", marginBottom: 14 }}>
        Connect a tool. <span style={{ fontStyle: "italic", fontWeight: 500 }}>The agent does the rest.</span>
      </div>
      <div style={{ fontFamily: theme.body, fontSize: 16, color: theme.inkLede, maxWidth: 620, marginBottom: 56 }}>
        Each connection gives Aki scoped access via Composio. OAuth happens on
        the provider&rsquo;s domain; we never see your password.
      </div>

      {err && (
        <div style={{ padding: "12px 18px", background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)", color: "#ee5959", fontFamily: theme.mono, fontSize: 12, marginBottom: 32 }}>
          {err}
        </div>
      )}

      {/* current */}
      {conns && conns.length > 0 && (
        <div style={{ marginBottom: 56 }}>
          <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 20 }}>
            active · {conns.length}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 18 }}>
            {conns.map((c) => (
              <div key={c.id} style={{ padding: "18px 20px", background: theme.bgSoft, border: `1px solid ${theme.hair}` }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                  <div style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 24, letterSpacing: "-0.015em" }}>
                    {c.provider}
                  </div>
                  <span style={{ fontFamily: theme.mono, fontSize: 10, color: c.status === "active" ? theme.accent : theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
                    {c.status}
                  </span>
                </div>
                <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, marginTop: 8, wordBreak: "break-all" }}>
                  {c.external_account_id}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* catalog */}
      <div>
        <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 20 }}>
          available
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 18 }}>
          {catalog.map((c) => {
            const already = conns?.some((x) => x.provider === c.provider && x.status === "active");
            return (
              <div key={c.provider} style={{ padding: "20px 22px", background: theme.bgSoft, border: `1px solid ${theme.hair}` }}>
                <div style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 28, letterSpacing: "-0.015em", marginBottom: 8 }}>
                  {c.name}
                </div>
                <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkLede, lineHeight: 1.5, marginBottom: 18 }}>
                  {c.blurb}
                </div>
                <button
                  onClick={() => connect(c.provider)}
                  disabled={busy === c.provider || already}
                  style={{
                    background: already ? "transparent" : theme.accent,
                    color: already ? theme.inkFaint : theme.bg,
                    border: already ? `1px solid ${theme.hair}` : "none",
                    fontFamily: theme.body, fontWeight: 600, fontSize: 13,
                    padding: "10px 18px", borderRadius: 999,
                    cursor: already ? "default" : "pointer",
                    opacity: busy === c.provider ? 0.5 : 1,
                  }}
                >
                  {already ? "Connected" : busy === c.provider ? "Redirecting…" : `Connect ${c.name}`}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
