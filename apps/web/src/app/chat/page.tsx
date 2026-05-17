"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner } from "@/components/AppShell";

type Msg = { role: "user" | "assistant"; content: string; tools?: ToolEvent[] };
type ToolEvent = { id: string; tool: string; status: string; label?: string };

type Stage = "idle" | "connecting" | "waking" | "thinking" | "tools-active" | "streaming";

/**
 * Chat surface over our /v1/chat/completions proxy.
 *
 * Parses OpenAI-format SSE chunks plus Hermes' inline tool.progress events.
 * No Vercel AI SDK — we want full control to surface tool events alongside
 * content deltas, and to render a live "what's happening" status bar.
 */
export default function ChatPage() {
  const { getToken } = useAuth();
  const [history, setHistory] = React.useState<Msg[]>([]);
  const [input, setInput] = React.useState("");
  const [streaming, setStreaming] = React.useState("");
  const [tools, setTools] = React.useState<ToolEvent[]>([]);
  const [stage, setStage] = React.useState<Stage>("idle");
  const [startedAt, setStartedAt] = React.useState<number | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);
  const stageRef = React.useRef<Stage>("idle");
  stageRef.current = stage;

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, streaming, tools, stage]);

  // Tick once a second while pending so elapsed-time bumps. After the first
  // 3 seconds with no first byte, escalate stage to 'waking' (cold-start hint).
  const [now, setNow] = React.useState(Date.now());
  React.useEffect(() => {
    if (stage === "idle") return;
    const t = setInterval(() => {
      setNow(Date.now());
      if (stageRef.current === "connecting" && startedAt && Date.now() - startedAt > 3000) {
        setStage("waking");
      }
    }, 250);
    return () => clearInterval(t);
  }, [stage, startedAt]);

  const pending = stage !== "idle";

  async function send() {
    const text = input.trim();
    if (!text || pending) return;
    setErr(null);

    const turn: Msg[] = [...history, { role: "user", content: text }];
    setHistory(turn);
    setInput("");
    setStreaming("");
    setTools([]);
    setStartedAt(Date.now());
    setStage("connecting");

    try {
      const token = await getToken({ template: "aki" });
      const wire = turn.map(({ role, content }) => ({ role, content }));

      // Frontend timeout: if the backend stalls (cold-start failure,
      // Composio down, etc.) the user shouldn't sit on "Connecting…"
      // forever. 90s ceiling covers worst-case cold-start + first turn.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 90_000);

      let r: Response;
      try {
        r = await fetch(`${API_URL}/v1/chat/completions`, {
          method: "POST",
          signal: controller.signal,
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ model: "hermes-agent", messages: wire, stream: true }),
        });
      } catch (fetchErr: unknown) {
        if (fetchErr instanceof Error && fetchErr.name === "AbortError") {
          throw new Error("Request timed out after 90s. The agent container may have failed to start. Try again, or check the backend logs.");
        }
        throw fetchErr;
      } finally {
        clearTimeout(timeoutId);
      }
      if (!r.ok || !r.body) throw new Error(`chat ${r.status}: ${await r.text()}`);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let tail = "";
      let assembled = "";
      const turnTools: ToolEvent[] = [];
      let sawFirstByte = false;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (!sawFirstByte) {
          sawFirstByte = true;
          setStage("thinking");
        }
        tail += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = tail.indexOf("\n\n")) !== -1) {
          const block = tail.slice(0, sep);
          tail = tail.slice(sep + 2);
          let evt = "message";
          const dataLines: string[] = [];
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) evt = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
          }
          if (!dataLines.length) continue;
          const data = dataLines.join("\n");
          if (data === "[DONE]") continue;
          try {
            const obj = JSON.parse(data);
            if (evt.startsWith("hermes.tool")) {
              const idx = turnTools.findIndex((x) => x.id === obj.toolCallId);
              const entry: ToolEvent = {
                id: obj.toolCallId, tool: obj.tool, status: obj.status, label: obj.label,
              };
              if (idx === -1) turnTools.push(entry);
              else turnTools[idx] = { ...turnTools[idx], ...entry, label: entry.label ?? turnTools[idx].label };
              setTools([...turnTools]);
              // Tools active until all completed; we don't go back from streaming → tools-active.
              if (stageRef.current !== "streaming") setStage("tools-active");
            } else if (typeof obj === "object" && obj !== null) {
              const delta = obj?.choices?.[0]?.delta?.content;
              if (typeof delta === "string") {
                assembled += delta;
                setStreaming(assembled);
                setStage("streaming");
              }
            }
          } catch { /* ignore non-JSON SSE */ }
        }
      }

      if (assembled || turnTools.length) {
        setHistory([...turn, { role: "assistant", content: assembled, tools: turnTools.length ? turnTools : undefined }]);
      }
      setStreaming("");
      setTools([]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setStage("idle");
      setStartedAt(null);
    }
  }

  const elapsed = startedAt ? Math.floor((now - startedAt) / 1000) : 0;
  const activeTool = tools.find((t) => t.status !== "completed") ?? tools[tools.length - 1];

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <div style={{ padding: "20px 56px", borderBottom: `1px solid ${theme.hair}`, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint }}>
            chat
          </div>
          <button onClick={() => { setHistory([]); setTools([]); setStreaming(""); setErr(null); }} style={{
            background: "transparent", color: theme.inkDim,
            border: `1px solid ${theme.hair}`,
            fontFamily: theme.body, fontSize: 12, fontWeight: 500,
            padding: "6px 14px", borderRadius: 999, cursor: "pointer",
          }}>New thread</button>
        </div>

        {err && <ErrorBanner>{err}</ErrorBanner>}

        <div style={{ flex: 1, overflowY: "auto", padding: "40px 0" }}>
          <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 32px" }}>
            {history.length === 0 && stage === "idle" && <EmptyChat onPick={(t) => setInput(t)}/>}
            {history.map((m, i) => <MessageBlock key={i} msg={m}/>)}

            {/* Status bar — shows live progress while a turn is in flight */}
            {pending && (
              <StatusBar stage={stage} elapsed={elapsed} activeTool={activeTool} toolCount={tools.length}/>
            )}

            {streaming && <MessageBlock msg={{ role: "assistant", content: streaming, tools: tools.length ? tools : undefined }}/>}

            <div ref={endRef}/>
          </div>
        </div>

        <div style={{ borderTop: `1px solid ${theme.hair}`, padding: "20px 0" }}>
          <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 32px" }}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="Ask Aki to do something with your connected tools…"
                disabled={pending}
                rows={2}
                style={{
                  flex: 1, resize: "none",
                  background: theme.bgSoft, color: theme.ink,
                  border: `1px solid ${theme.hair}`, borderRadius: 6,
                  padding: "12px 14px",
                  fontFamily: theme.body, fontSize: 15, lineHeight: 1.45,
                  outline: "none",
                }}
              />
              <button
                onClick={send}
                disabled={pending || !input.trim()}
                style={{
                  background: theme.accent, color: theme.bg, border: "none",
                  fontFamily: theme.body, fontWeight: 600, fontSize: 14,
                  padding: "12px 22px", borderRadius: 999,
                  cursor: pending ? "default" : "pointer",
                  opacity: pending || !input.trim() ? 0.5 : 1,
                }}
              >
                {pending ? "…" : "Send"}
              </button>
            </div>
            <div style={{ marginTop: 8, fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
              enter to send · shift+enter for newline
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function StatusBar({ stage, elapsed, activeTool, toolCount }: { stage: Stage; elapsed: number; activeTool?: ToolEvent; toolCount: number }) {
  const { headline, sub } = describe(stage, elapsed, activeTool, toolCount);
  return (
    <div style={{
      marginBottom: 24,
      padding: "14px 18px",
      background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      borderLeft: `2px solid ${theme.accent}`,
      display: "flex", alignItems: "center", gap: 16,
    }}>
      <Pulse/>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: theme.body, fontSize: 14, fontWeight: 500, color: theme.ink }}>
          {headline}
        </div>
        {sub && (
          <div style={{ marginTop: 4, fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, wordBreak: "break-all" }}>
            {sub}
          </div>
        )}
      </div>
      <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em" }}>
        {elapsed}s
      </div>
    </div>
  );
}

function describe(stage: Stage, elapsed: number, activeTool: ToolEvent | undefined, toolCount: number): { headline: string; sub?: string } {
  if (stage === "connecting") return { headline: "Connecting to Aki…" };
  if (stage === "waking") return {
    headline: "Waking up your agent…",
    sub: elapsed > 8 ? "first chat in 15+ minutes spins up a fresh container (~10s)" : "this happens after idle periods",
  };
  if (stage === "thinking") return { headline: "Thinking…" };
  if (stage === "tools-active") {
    return {
      headline: activeTool ? `Running ${activeTool.tool}…` : "Calling tools…",
      sub: activeTool?.label || (toolCount > 1 ? `${toolCount} tool calls so far` : undefined),
    };
  }
  if (stage === "streaming") return { headline: "Streaming reply…" };
  return { headline: "Working…" };
}

function Pulse() {
  return (
    <span style={{
      width: 8, height: 8, borderRadius: "50%", background: theme.accent,
      animation: "akiPulse 1.4s ease-in-out infinite",
    }}/>
  );
}

function EmptyChat({ onPick }: { onPick: (text: string) => void }) {
  const examples = [
    "List my 5 most recent emails — just sender and subject.",
    "Find anything about 'invoice' from the last 14 days.",
    "Use code execution to compute fibonacci(20).",
  ];
  return (
    <div style={{ paddingTop: 80, textAlign: "center" }}>
      <div style={{ fontFamily: theme.display, fontStyle: "italic", fontSize: 36, fontWeight: 500, letterSpacing: "-0.02em", color: theme.inkLede, marginBottom: 32 }}>
        Ask Aki something.
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 560, margin: "0 auto" }}>
        {examples.map((e) => (
          <button key={e} onClick={() => onPick(e)} style={{
            padding: "12px 16px",
            background: "transparent",
            border: `1px dashed ${theme.hair}`,
            color: theme.inkDim,
            fontFamily: theme.body, fontSize: 14,
            textAlign: "left", cursor: "pointer",
            transition: "border-color 0.15s ease, color 0.15s ease",
          }}
          onMouseEnter={(e2) => { e2.currentTarget.style.borderColor = theme.accent; e2.currentTarget.style.color = theme.ink; }}
          onMouseLeave={(e2) => { e2.currentTarget.style.borderColor = theme.hair; e2.currentTarget.style.color = theme.inkDim; }}
          >
            {e}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBlock({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  const [copied, setCopied] = React.useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {/* ignore */}
  }
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontFamily: theme.mono, fontSize: 10, color: isUser ? theme.inkDim : theme.accent, letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 8 }}>
        {isUser ? "you" : "aki"}
      </div>
      <div style={{
        fontFamily: theme.body, fontSize: 16, lineHeight: 1.6,
        color: isUser ? theme.inkLede : theme.ink,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>
        {msg.content || (isUser ? "" : <span style={{ color: theme.inkFaint }}>…</span>)}
      </div>
      {msg.tools && msg.tools.length > 0 && <ToolPanel tools={msg.tools}/>}
      {!isUser && msg.content && (
        <div style={{ marginTop: 12, display: "flex", gap: 14, alignItems: "center" }}>
          <button onClick={copy} style={{
            background: "transparent", border: "none", padding: 0, cursor: "pointer",
            fontFamily: theme.mono, fontSize: 11, color: copied ? theme.accent : theme.inkFaint,
            letterSpacing: "0.18em", textTransform: "uppercase",
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <CopyIcon/> {copied ? "copied" : "copy"}
          </button>
          <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
            · done
          </span>
        </div>
      )}
    </div>
  );
}

function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2"/>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
    </svg>
  );
}

function ToolPanel({ tools }: { tools: ToolEvent[] }) {
  const grouped: Record<string, ToolEvent> = {};
  for (const t of tools) {
    grouped[t.id] = { ...grouped[t.id], ...t, label: t.label ?? grouped[t.id]?.label };
  }
  const rows = Object.values(grouped);
  return (
    <div style={{
      marginTop: 12,
      padding: "12px 16px",
      background: "rgba(197,236,79,0.04)",
      border: `1px solid ${theme.accentDim}`,
      borderRadius: 4,
    }}>
      <div style={{ fontFamily: theme.mono, fontSize: 10, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.accent, marginBottom: 10 }}>
        tools · {rows.length}
      </div>
      {rows.map((t) => (
        <div key={t.id} style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 6, fontFamily: theme.mono, fontSize: 12, color: theme.inkLede }}>
          <span style={{ color: t.status === "completed" ? theme.accent : theme.inkDim, fontSize: 10, lineHeight: "20px" }}>
            {t.status === "completed" ? "●" : "◌"}
          </span>
          <span style={{ minWidth: 180, color: theme.ink, flexShrink: 0 }}>{t.tool}</span>
          {t.label && (
            <span title={t.label} style={{
              color: theme.inkDim, fontSize: 11, flex: 1, minWidth: 0,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{t.label}</span>
          )}
        </div>
      ))}
    </div>
  );
}
