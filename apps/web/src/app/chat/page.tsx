"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton, useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";

type Msg = { role: "user" | "assistant"; content: string };
type ToolEvent = { id: string; tool: string; status: string; label?: string };

/**
 * Chat surface over our /v1/chat/completions proxy.
 *
 * We parse OpenAI-format SSE chunks plus Hermes' inline tool.progress
 * events. No Vercel AI SDK — we want full control because we need to
 * surface tool events alongside content deltas.
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
      const r = await fetch(`${API_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: "hermes-agent",
          messages: turn,
          stream: true,
        }),
      });
      if (!r.ok || !r.body) throw new Error(`chat ${r.status}: ${await r.text()}`);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let tail = "";
      let assembled = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        tail += decoder.decode(value, { stream: true });
        let sep;
        // SSE block separator is a blank line.
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
              setTools((t) => {
                const idx = t.findIndex((x) => x.id === obj.toolCallId);
                const entry: ToolEvent = {
                  id: obj.toolCallId,
                  tool: obj.tool,
                  status: obj.status,
                  label: obj.label,
                };
                if (idx === -1) return [...t, entry];
                const copy = [...t];
                // Preserve label from earlier event if the new one omits it.
                copy[idx] = { ...copy[idx], ...entry, label: entry.label ?? copy[idx].label };
                return copy;
              });
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

      if (assembled) {
        setHistory([...turn, { role: "assistant", content: assembled }]);
      }
      setStreaming("");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "flex", flexDirection: "column",
      background: theme.bg, color: theme.ink, fontFamily: theme.body,
    }}>
      {/* nav */}
      <nav style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 56px", borderBottom: `1px solid ${theme.hair}` }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 14, textDecoration: "none", color: theme.ink }}>
          <span style={{ display: "inline-block", width: 24, height: 24, fontFamily: theme.display, fontWeight: 700, fontSize: 30, lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em" }}>a</span>
          <span style={{ fontFamily: theme.body, fontWeight: 600, fontSize: 15, letterSpacing: "0.04em" }}>aki</span>
        </Link>
        <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
          <Link href="/chat" style={{ color: theme.accent, textDecoration: "none", fontSize: 14, fontWeight: 500 }}>Chat</Link>
          <Link href="/connect" style={{ color: theme.inkDim, textDecoration: "none", fontSize: 14, fontWeight: 500 }}>Connect</Link>
          <UserButton/>
        </div>
      </nav>

      {/* messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "32px 0" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 32px" }}>
          {history.length === 0 && !streaming && (
            <div style={{ paddingTop: 80, textAlign: "center", color: theme.inkFaint, fontFamily: theme.display, fontStyle: "italic", fontSize: 28, fontWeight: 500, letterSpacing: "-0.015em" }}>
              Ask Aki something.
            </div>
          )}
          {history.map((m, i) => (
            <Message key={i} role={m.role} content={m.content}/>
          ))}
          {streaming && <Message role="assistant" content={streaming}/>}
          {tools.length > 0 && (
            <div style={{ marginTop: 16, padding: "12px 16px", background: theme.bgSoft, border: `1px solid ${theme.hair}`, borderRadius: 6 }}>
              <div style={{ fontFamily: theme.mono, fontSize: 10, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 8 }}>
                tool calls · {tools.length}
              </div>
              {tools.map((t) => (
                <div key={t.id} style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 6, fontFamily: theme.mono, fontSize: 12, color: theme.inkLede }}>
                  <span style={{ color: t.status === "completed" ? theme.accent : theme.inkDim }}>●</span>
                  <span style={{ minWidth: 130 }}>{t.tool}</span>
                  <span style={{ color: theme.inkDim, fontSize: 11, wordBreak: "break-all" }}>{t.label || t.status}</span>
                </div>
              ))}
            </div>
          )}
          {err && (
            <div style={{ marginTop: 16, padding: "12px 18px", background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)", color: "#ee5959", fontFamily: theme.mono, fontSize: 12 }}>
              {err}
            </div>
          )}
          <div ref={endRef}/>
        </div>
      </div>

      {/* composer */}
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
  );
}

function Message({ role, content }: { role: "user" | "assistant"; content: string }) {
  const isUser = role === "user";
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 6 }}>
        {isUser ? "you" : "aki"}
      </div>
      <div style={{
        fontFamily: theme.body, fontSize: 16, lineHeight: 1.55,
        color: isUser ? theme.inkLede : theme.ink,
        whiteSpace: "pre-wrap",
      }}>
        {content}
      </div>
    </div>
  );
}
