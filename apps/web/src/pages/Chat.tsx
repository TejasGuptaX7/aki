"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Copy, Check, Bot, User } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { API_URL, theme } from "@/theme"
import ErrorBanner from "@/components/ErrorBanner"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  toolCalls?: ToolCall[]
  timestamp: Date
}

interface ToolCall {
  id: string
  name: string
  arguments: string
  result?: string
}

export default function Chat() {
  const { getToken } = useAuthToken()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [status, setStatus] = useState<"idle" | "connecting" | "streaming">("idle")
  const [err, setErr] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [model, setModel] = useState("gpt-4")
  const [lastCost, setLastCost] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  const sendMessage = useCallback(async () => {
    if (!input.trim() || status !== "idle") return
    setErr(null)

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    }

    const assistantId = `assistant-${Date.now()}`
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      toolCalls: [],
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput("")
    setStatus("connecting")
    if (textareaRef.current) textareaRef.current.style.height = "auto"

    try {
      const token = await getToken({ template: "aki" })
      const res = await fetch(`${API_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          messages: [...messages, userMsg].map((m) => ({
            role: m.role,
            content: m.content,
          })),
          stream: true,
          model,
        }),
      })

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }

      setStatus("streaming")
      const reader = res.body?.getReader()
      if (!reader) throw new Error("No response body")

      const decoder = new TextDecoder()
      let buffer = ""
      let currentContent = ""
      let currentToolCalls: ToolCall[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith("data: ")) continue
          const data = trimmed.slice(6)
          if (data === "[DONE]") continue

          try {
            const parsed = JSON.parse(data)
            const delta = parsed.choices?.[0]?.delta

            if (delta?.content) {
              currentContent += delta.content
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: currentContent, toolCalls: currentToolCalls } : m
                )
              )
            }

            if (delta?.tool_calls) {
              for (const tc of delta.tool_calls) {
                const existing = currentToolCalls.find((t) => t.id === tc.id)
                if (existing) {
                  existing.arguments += tc.function?.arguments || ""
                } else {
                  currentToolCalls.push({
                    id: tc.id || `tc-${Date.now()}`,
                    name: tc.function?.name || "unknown",
                    arguments: tc.function?.arguments || "",
                  })
                }
              }
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: currentContent, toolCalls: currentToolCalls } : m
                )
              )
            }

            if (parsed.usage?.total_tokens) {
              setLastCost(parsed.usage.total_tokens * 0.00001)
            }
          } catch {
            // ignore parse errors for malformed chunks
          }
        }
      }

      setStatus("idle")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to send message")
      setStatus("idle")
      setMessages((prev) => prev.filter((m) => m.id !== assistantId))
    }
  }, [input, status, messages, model, getToken])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const copyToClipboard = async (content: string, id: string) => {
    await navigator.clipboard.writeText(content)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 56px - 48px)" }}>
      {err && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBanner message={err} onRetry={() => setErr(null)} />
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          paddingBottom: 16,
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
            }}
          >
            <Bot size={40} color={theme.inkFaint} />
            <div style={{ fontFamily: theme.display, fontSize: 20, color: theme.inkFaint }}>
              Start a conversation
            </div>
            <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim }}>
              Send a message to begin chatting with the AI agent
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: "flex",
              flexDirection: msg.role === "user" ? "row-reverse" : "row",
              gap: 10,
              alignItems: "flex-start",
            }}
          >
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 999,
                background: msg.role === "assistant" ? theme.accentDim : theme.hairSoft,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                marginTop: 2,
              }}
            >
              {msg.role === "assistant" ? <Bot size={14} color={theme.accent} /> : <User size={14} color={theme.inkDim} />}
            </div>
            <div
              style={{
                maxWidth: "70%",
                background: msg.role === "user" ? theme.accentDim : theme.bgSoft,
                border: "1px solid " + (msg.role === "user" ? "rgba(197,236,79,0.2)" : theme.hair),
                borderRadius: 12,
                padding: "12px 16px",
                position: "relative",
              }}
            >
              <div
                style={{
                  fontFamily: theme.body,
                  fontSize: 14,
                  lineHeight: 1.6,
                  color: theme.ink,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {msg.content || (msg.role === "assistant" && status === "streaming" ? (
                  <span style={{ color: theme.inkFaint }}>Thinking...</span>
                ) : null)}
              </div>

              {/* Tool Calls */}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                  {msg.toolCalls.map((tc) => (
                    <div
                      key={tc.id}
                      style={{
                        background: theme.bg,
                        border: "1px solid " + theme.hair,
                        borderRadius: 8,
                        padding: 10,
                      }}
                    >
                      <div
                        style={{
                          fontFamily: theme.mono,
                          fontSize: 11,
                          color: theme.accent,
                          textTransform: "uppercase",
                          letterSpacing: "0.08em",
                          marginBottom: 4,
                        }}
                      >
                        Tool: {tc.name}
                      </div>
                      <pre
                        style={{
                          fontFamily: theme.mono,
                          fontSize: 11,
                          color: theme.inkDim,
                          margin: 0,
                          overflow: "auto",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {tc.arguments}
                      </pre>
                    </div>
                  ))}
                </div>
              )}

              {/* Copy button on assistant messages */}
              {msg.role === "assistant" && msg.content && (
                <button
                  onClick={() => copyToClipboard(msg.content, msg.id)}
                  style={{
                    position: "absolute",
                    top: 6,
                    right: 6,
                    background: "transparent",
                    border: "none",
                    color: theme.inkFaint,
                    cursor: "pointer",
                    padding: 4,
                    opacity: 0.6,
                  }}
                  title="Copy"
                >
                  {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Status Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "8px 0",
          fontFamily: theme.mono,
          fontSize: 11,
          color: theme.inkFaint,
          borderTop: "1px solid " + theme.hair,
        }}
      >
        <span>Status: {status}</span>
        <span>Model: {model}</span>
        {lastCost !== null && <span>Last turn: ${lastCost.toFixed(4)}</span>}
      </div>

      {/* Input */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 10,
          borderTop: "1px solid " + theme.hair,
          paddingTop: 12,
        }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value)
            e.target.style.height = "auto"
            e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px"
          }}
          onKeyDown={handleKeyDown}
          placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
          style={{
            flex: 1,
            minHeight: 40,
            maxHeight: 200,
            background: theme.bg,
            border: "1px solid " + theme.hair,
            borderRadius: 8,
            color: theme.ink,
            padding: "10px 14px",
            fontFamily: theme.body,
            fontSize: 14,
            resize: "none",
            outline: "none",
          }}
          onFocus={(e) => {
            e.target.style.borderColor = theme.accent
          }}
          onBlur={(e) => {
            e.target.style.borderColor = theme.hair
          }}
        />
        <button
          onClick={sendMessage}
          disabled={!input.trim() || status !== "idle"}
          style={{
            background: theme.accent,
            color: theme.bg,
            border: "none",
            borderRadius: 999,
            padding: "10px 20px",
            fontFamily: theme.body,
            fontSize: 14,
            fontWeight: 500,
            cursor: input.trim() && status === "idle" ? "pointer" : "not-allowed",
            opacity: input.trim() && status === "idle" ? 1 : 0.4,
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexShrink: 0,
            height: 40,
          }}
        >
          <Send size={14} />
          Send
        </button>
      </div>
    </div>
  )
}
