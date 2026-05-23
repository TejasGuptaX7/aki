"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";

type Device = {
  id: string;
  name: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

export default function DevicesPage() {
  const { getToken } = useAuth();
  const [devices, setDevices] = React.useState<Device[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const [code, setCode] = React.useState<{ code: string; expiresIn: number } | null>(null);
  const [generating, setGenerating] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/devices`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`devices ${r.status}: ${await r.text()}`);
      setDevices(await r.json());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [getToken]);

  React.useEffect(() => { refresh(); }, [refresh]);
  // After a successful pair, the desktop's call updates last_seen_at; poll
  // every 10s so the new device shows up promptly.
  React.useEffect(() => {
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function generateCode() {
    setGenerating(true);
    setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/devices/pair/start`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`pair/start ${r.status}: ${await r.text()}`);
      const data = await r.json();
      setCode({ code: data.code, expiresIn: data.expires_in_seconds });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function revoke(id: string) {
    if (!confirm("Revoke this device? It will need to be paired again.")) return;
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/devices/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`revoke ${r.status}`);
      refresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <AppShell>
      <SectionHeader
        kicker="devices"
        title={<>Pair a laptop. <span style={{ fontStyle: "italic", fontWeight: 500, color: theme.inkDim }}>Aki on the desktop.</span></>}
        lede="Pair the Aki desktop app to your account. Each pair gets a long-lived device token; revoke any time."
      />
      <div style={{ padding: "32px 56px" }}>
        {err && <ErrorBanner>{err}</ErrorBanner>}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 40 }}>
          <div>
            <Kicker>paired devices</Kicker>
            <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 1, background: theme.hair }}>
              {devices.length === 0 ? (
                <div style={{
                  background: theme.bg, padding: "40px 20px", textAlign: "center",
                  fontFamily: theme.body, fontSize: 13, color: theme.inkFaint,
                }}>
                  No devices paired yet.
                </div>
              ) : devices.map((d) => (
                <div key={d.id} style={{
                  background: theme.bg, padding: "16px 20px",
                  display: "grid", gridTemplateColumns: "1fr 200px 100px",
                  gap: 16, alignItems: "center",
                }}>
                  <div>
                    <div style={{ fontFamily: theme.body, fontSize: 15, color: d.revoked_at ? theme.inkFaint : theme.ink }}>
                      {d.name}
                    </div>
                    <div style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.16em", marginTop: 2 }}>
                      paired {new Date(d.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim }}>
                    {d.revoked_at ? (
                      <span style={{ color: theme.inkFaint }}>revoked</span>
                    ) : d.last_seen_at ? (
                      `last seen ${relative(d.last_seen_at)}`
                    ) : (
                      <span style={{ color: theme.inkFaint }}>never seen</span>
                    )}
                  </div>
                  {!d.revoked_at && (
                    <button onClick={() => revoke(d.id)} style={{
                      background: "transparent", color: "#ee5959",
                      border: "1px solid rgba(238,89,89,0.32)",
                      padding: "6px 14px", fontFamily: theme.body, fontSize: 12,
                      cursor: "pointer", borderRadius: 999,
                    }}>
                      Revoke
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <aside>
            <Kicker>pair new device</Kicker>
            <div style={{
              marginTop: 14, padding: "20px 22px",
              background: theme.bgSoft, border: `1px solid ${theme.hair}`,
            }}>
              {code ? (
                <PairCodeView code={code} onReset={() => setCode(null)}/>
              ) : (
                <>
                  <p style={{ margin: "0 0 16px",
                              fontFamily: theme.body, fontSize: 13,
                              color: theme.inkLede, lineHeight: 1.5 }}>
                    Generate a 6-digit code, then enter it in the Aki desktop
                    app. The code expires in 5 minutes.
                  </p>
                  <button onClick={generateCode} disabled={generating} style={{
                    width: "100%",
                    background: theme.accent, color: theme.bg, border: "none",
                    fontFamily: theme.body, fontWeight: 600, fontSize: 14,
                    padding: "12px 18px", borderRadius: 999,
                    cursor: generating ? "default" : "pointer",
                    opacity: generating ? 0.5 : 1,
                  }}>
                    {generating ? "Generating…" : "Generate pairing code"}
                  </button>
                </>
              )}
            </div>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

function PairCodeView({ code, onReset }: { code: { code: string; expiresIn: number }; onReset: () => void }) {
  const [secs, setSecs] = React.useState(code.expiresIn);
  React.useEffect(() => {
    const t = setInterval(() => setSecs((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div>
      <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 10 }}>
        code
      </div>
      <div style={{
        fontFamily: theme.mono, fontSize: 40, color: theme.accent,
        letterSpacing: "0.18em", textAlign: "center",
        padding: "10px 0", borderTop: `1px solid ${theme.hair}`, borderBottom: `1px solid ${theme.hair}`,
      }}>
        {code.code.replace(/(\d{3})(\d{3})/, "$1 $2")}
      </div>
      <div style={{ marginTop: 12, fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, textAlign: "center", letterSpacing: "0.16em" }}>
        expires in {secs}s
      </div>
      <button onClick={onReset} style={{
        marginTop: 18, width: "100%",
        background: "transparent", color: theme.inkDim,
        border: `1px solid ${theme.hair}`,
        padding: "8px 14px", fontFamily: theme.body, fontSize: 13,
        cursor: "pointer", borderRadius: 999,
      }}>
        New code
      </button>
    </div>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.22em", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function relative(iso: string): string {
  const t = Date.now() - new Date(iso).getTime();
  if (t < 60_000) return "just now";
  if (t < 3_600_000) return `${Math.floor(t / 60_000)}m ago`;
  if (t < 86_400_000) return `${Math.floor(t / 3_600_000)}h ago`;
  return `${Math.floor(t / 86_400_000)}d ago`;
}
