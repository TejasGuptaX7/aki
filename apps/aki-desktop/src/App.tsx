import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { theme } from "./lib/theme";
import { useChat } from "./hooks/useChat";
import { ChatSurface } from "./components/ChatSurface";
import { ChatInput } from "./components/ChatInput";

type Status = "pairing" | "paired" | "ready";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string) || "http://localhost:8000";

export function App() {
  const [status, setStatus] = useState<Status>("pairing");
  const [code, setCode] = useState("");
  const [name, setName] = useState(deriveDeviceName());
  const [err, setErr] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);

  const chat = useChat();

  // On launch, if already paired, jump straight to ready.
  useEffect(() => {
    invoke("is_paired")
      .then((paired: unknown) => {
        if (paired) {
          setStatus("paired");
          setTimeout(() => setStatus("ready"), 700);
        }
      })
      .catch(() => {
        /* ignore */
      });
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
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100vh",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "20px 56px",
            borderBottom: `1px solid ${theme.hair}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
          }}
        >
          <div
            style={{
              fontFamily: theme.mono,
              fontSize: 11,
              letterSpacing: "0.24em",
              textTransform: "uppercase",
              color: theme.inkFaint,
            }}
          >
            chat
          </div>
          <button
            onClick={chat.clear}
            style={{
              background: "transparent",
              color: theme.inkDim,
              border: `1px solid ${theme.hair}`,
              fontFamily: theme.body,
              fontSize: 12,
              fontWeight: 500,
              padding: "6px 14px",
              borderRadius: 999,
              cursor: "pointer",
            }}
          >
            New thread
          </button>
        </div>

        {/* Error banner */}
        {chat.err && (
          <div
            style={{
              padding: "12px 56px",
              background: "rgba(238,89,89,0.08)",
              borderBottom: "1px solid rgba(238,89,89,0.2)",
              color: "#ee5959",
              fontSize: 13,
            }}
          >
            {chat.err}
          </div>
        )}

        {/* Messages */}
        <ChatSurface
          history={chat.history}
          streaming={chat.streaming}
          tools={chat.tools}
          stage={chat.stage}
          pending={chat.pending}
          elapsed={chat.elapsed}
          activeTool={chat.activeTool}
          onPickExample={chat.setInput}
        />

        {/* Input */}
        <ChatInput
          input={chat.input}
          onChange={chat.setInput}
          onSend={chat.send}
          pending={chat.pending}
        />
      </div>
    );
  }

  return (
    <div
      style={{
        padding: "40px 36px",
        height: "100vh",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          fontSize: 48,
          lineHeight: 0.78,
          letterSpacing: "-0.04em",
          fontFamily: theme.display,
          fontWeight: 700,
          marginBottom: 12,
        }}
      >
        a
      </div>
      <div
        style={{
          fontSize: 14,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: theme.inkFaint,
          marginBottom: 32,
        }}
      >
        aki desktop
      </div>

      <div style={{ width: "100%", maxWidth: 360 }}>
        <Label>device name</Label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={inputStyle}
        />
        <div style={{ height: 16 }} />
        <Label>pairing code</Label>
        <input
          value={code}
          onChange={(e) =>
            setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
          }
          placeholder="000000"
          style={{
            ...inputStyle,
            fontFamily: theme.mono,
            fontSize: 22,
            letterSpacing: "0.4em",
            textAlign: "center",
          }}
          autoFocus
        />
        {err && (
          <div style={{ marginTop: 12, color: "#ee5959", fontSize: 12 }}>
            {err}
          </div>
        )}
        <button
          onClick={pair}
          disabled={pairing || code.length !== 6 || !name.trim()}
          style={{
            marginTop: 24,
            width: "100%",
            background: theme.accent,
            color: theme.bg,
            border: "none",
            padding: "12px 18px",
            borderRadius: 999,
            fontWeight: 600,
            fontSize: 14,
            opacity: pairing || code.length !== 6 || !name.trim() ? 0.5 : 1,
          }}
        >
          {pairing ? "Pairing…" : "Pair this device"}
        </button>
        <div
          style={{
            marginTop: 16,
            fontSize: 11,
            color: theme.inkFaint,
            textAlign: "center",
            letterSpacing: "0.12em",
          }}
        >
          generate the code in the web app:{" "}
          <span style={{ color: theme.accent }}>/devices</span>
        </div>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        color: theme.inkFaint,
        letterSpacing: "0.2em",
        textTransform: "uppercase",
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: theme.bgSoft,
  color: theme.ink,
  border: `1px solid ${theme.hair}`,
  borderRadius: 4,
  padding: "10px 14px",
  fontSize: 14,
  outline: "none",
};

function deriveDeviceName() {
  if (typeof navigator !== "undefined" && navigator.platform) {
    return `${navigator.platform.split(/\s+/)[0]} laptop`;
  }
  return "My laptop";
}
