"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner } from "@/components/AppShell";

type Msg = { role: "user" | "assistant"; content: string; tools?: ToolEvent[] };
type ToolEvent = { id: string; tool: string; status: string; label?: string };

/**
 * Chat surface over our /v1/chat/completions proxy.
 *
 * Parses OpenAI-format SSE chunks plus Hermes' inline tool.progress events.
 * No Vercel AI SDK — we want full control to surface tool events alongside
 * content deltas.
 */
export default function ChatPage() {
  const { getToken } = useAuth();
  const [history, setHistory] = React.useState<Msg[]>([]);
  const [input, setInput] = React.useState("");
  const [streaming, setStreaming] = React.useState("");
  const [tools, setTools] = React.useState<ToolEvent[]>([]);
  const [pending, setPending] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, streaming, tools]);

  async function send() {
    const text = input.trim();
    if (!text || pending) return;
    setErr(null);

    const turn: Msg[] = [...history, { role: "user", content: text }];
    setHistory(turn);
    setInput("");
    setStreaming("");
    setTools([]);
    setPending(true);

    try {
      const token = await getToken({ template: "aki" });
      // Strip our local-only fields before sending upstream.
      const wire = turn.map(({ role, content }) => ({ role, content }));
      const r = await fetch(`${API_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ model: "hermes-agent", messages: wire, stream: true }),
      });
      if (!r.ok || !r.body) throw new Error(`chat ${r.status}: ${await r.text()}`);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let tail = "";
      let assembled = "";
      const turnTools: ToolEvent[] = [];

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
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
            } else if (typeof obj === "object" && obj !== null) {
              const delta = obj?.choices?.[0]?.delta?.content;
              if (typeof delta === "string") {
                assembled += delta;
                setStreaming(assembled);
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
      setPending(false);
    }
  }

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <div style={{ padding: "20px 56px", borderBottom: `1px solid ${theme.hair}`, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint }}>
            chat · streaming
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
            {history.length === 0 && !streaming && (
              <EmptyChat/>
            )}
            {history.map((m, i) => (
              <MessageBlock key={i} msg={m}/>
            ))}
            {streaming && <MessageBlock msg={{ role: "assistant", content: streaming, tools: tools.length ? tools : undefined }}/>}
            {!streaming && tools.length > 0 && <ToolPanel tools={tools}/>}
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

function EmptyChat() {
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
          <div key={e} style={{
            padding: "12px 16px",
            border: `1px dashed ${theme.hair}`,
            color: theme.inkDim,
            fontFamily: theme.body, fontSize: 14,
            textAlign: "left",
          }}>
            {e}
          </div>
        ))}
      </div>
    </div>
  );
}

function MessageBlock({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontFamily: theme.mono, fontSize: 10, color: isUser ? theme.inkDim : theme.accent, letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 8 }}>
        {isUser ? "you" : "aki"}
      </div>
      <div style={{
        fontFamily: isUser ? theme.body : theme.body, fontSize: 16, lineHeight: 1.6,
        color: isUser ? theme.inkLede : theme.ink,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>
        {msg.content || (isUser ? "" : <span style={{ color: theme.inkFaint }}>…</span>)}
      </div>
      {msg.tools && msg.tools.length > 0 && <ToolPanel tools={msg.tools} compact/>}
    </div>
  );
}

function ToolPanel({ tools, compact }: { tools: ToolEvent[]; compact?: boolean }) {
  // Group by toolCallId so running/completed pairs render as one row.
  const grouped: Record<string, ToolEvent> = {};
  for (const t of tools) {
    grouped[t.id] = { ...grouped[t.id], ...t, label: t.label ?? grouped[t.id]?.label };
  }
  const rows = Object.values(grouped);
  return (
    <div style={{
      marginTop: compact ? 12 : 16,
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
          <span style={{ minWidth: 180, color: theme.ink }}>{t.tool}</span>
          {t.label && (
            <span style={{ color: theme.inkDim, fontSize: 11, wordBreak: "break-all", flex: 1 }}>{t.label}</span>
          )}
        </div>
      ))}
    </div>
  );
}
