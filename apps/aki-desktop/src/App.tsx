import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type Status = "pairing" | "paired" | "ready";

const API_BASE = (import.meta.env.VITE_API_BASE as string) || "http://localhost:8000";

export function App() {
  const [status, setStatus] = useState<Status>("pairing");
  const [code, setCode] = useState("");
  const [name, setName] = useState(deriveDeviceName());
  const [err, setErr] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);

  // On launch, if we already have a device JWT in keychain, jump straight
  // to ready. Stub: assume not paired until pair_device returns.
  useEffect(() => {
    // TODO: invoke a getter that checks for an existing device JWT.
  }, []);

  async function pair() {
    setErr(null);
    setPairing(true);
    try {
      await invoke("pair_device", { code, name, apiBase: API_BASE });
      setStatus("paired");
      setTimeout(() => setStatus("ready"), 700);
    } catch (e) {
      setErr(typeof e === "string" ? e : String(e));
    } finally {
      setPairing(false);
    }
  }

  if (status === "ready") {
    return <ChatStub/>;
  }

  return (
    <div style={{
      padding: "40px 36px", height: "100vh", boxSizing: "border-box",
      display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center",
    }}>
      <div style={{
        fontSize: 48, lineHeight: 0.78, letterSpacing: "-0.04em",
        fontFamily: "serif", fontWeight: 700, marginBottom: 12,
      }}>a</div>
      <div style={{ fontSize: 14, letterSpacing: "0.18em", textTransform: "uppercase", color: "var(--ink-faint)", marginBottom: 32 }}>
        aki desktop
      </div>

      <div style={{ width: "100%", maxWidth: 360 }}>
        <Label>device name</Label>
        <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle}/>
        <div style={{ height: 16 }}/>
        <Label>pairing code</Label>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="000000"
          style={{ ...inputStyle, fontFamily: "ui-monospace, monospace", fontSize: 22, letterSpacing: "0.4em", textAlign: "center" }}
          autoFocus
        />
        {err && <div style={{ marginTop: 12, color: "#ee5959", fontSize: 12 }}>{err}</div>}
        <button
          onClick={pair}
          disabled={pairing || code.length !== 6 || !name.trim()}
          style={{
            marginTop: 24, width: "100%",
            background: "var(--accent)", color: "var(--bg)", border: "none",
            padding: "12px 18px", borderRadius: 999, fontWeight: 600, fontSize: 14,
            opacity: pairing || code.length !== 6 || !name.trim() ? 0.5 : 1,
          }}
        >
          {pairing ? "Pairing…" : "Pair this device"}
        </button>
        <div style={{ marginTop: 16, fontSize: 11, color: "var(--ink-faint)", textAlign: "center", letterSpacing: "0.12em" }}>
          generate the code in the web app: <span style={{ color: "var(--accent)" }}>/devices</span>
        </div>
      </div>
    </div>
  );
}

function ChatStub() {
  return (
    <div style={{ padding: 40 }}>
      <h2 style={{ marginTop: 0, fontWeight: 500 }}>Paired.</h2>
      <p style={{ color: "var(--ink-dim)", fontSize: 14, lineHeight: 1.6 }}>
        Aki is connected to your account. The chat surface and local agent
        will land in the next desktop release.
      </p>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11, color: "var(--ink-faint)", letterSpacing: "0.2em", textTransform: "uppercase", marginBottom: 6 }}>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box",
  background: "var(--bg-soft)", color: "var(--ink)",
  border: "1px solid var(--hair)", borderRadius: 4,
  padding: "10px 14px", fontSize: 14, outline: "none",
};

function deriveDeviceName() {
  // Best-effort default. The user can edit before pairing.
  if (typeof navigator !== "undefined" && navigator.platform) {
    return `${navigator.platform.split(/\s+/)[0]} laptop`;
  }
  return "My laptop";
}
