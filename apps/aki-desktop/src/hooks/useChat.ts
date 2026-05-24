import { useState, useRef, useEffect, useCallback } from "react";
import { sendChatMessage } from "../lib/api";

export type ToolEvent = {
  id: string;
  tool: string;
  status: string;
  label?: string;
};

export type Msg = {
  role: "user" | "assistant";
  content: string;
  tools?: ToolEvent[];
};

export type Stage =
  | "idle"
  | "connecting"
  | "waking"
  | "thinking"
  | "tools-active"
  | "streaming";

export function useChat() {
  const [history, setHistory] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState("");
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [stage, setStage] = useState<Stage>("idle");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const stageRef = useRef<Stage>("idle");
  stageRef.current = stage;

  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (stage === "idle") return;
    const t = setInterval(() => {
      setNow(Date.now());
      if (
        stageRef.current === "connecting" &&
        startedAt &&
        Date.now() - startedAt > 3000
      ) {
        setStage("waking");
      }
    }, 250);
    return () => clearInterval(t);
  }, [stage, startedAt]);

  const pending = stage !== "idle";

  const send = useCallback(async () => {
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
      const wire = turn.map(({ role, content }) => ({ role, content }));
      let tail = "";
      let assembled = "";
      const turnTools: ToolEvent[] = [];
      let sawFirstByte = false;

      await sendChatMessage(wire, (chunkText) => {
        if (!sawFirstByte) {
          sawFirstByte = true;
          setStage("thinking");
        }
        tail += chunkText;
        let sep;
        while ((sep = tail.indexOf("\n\n")) !== -1) {
          const block = tail.slice(0, sep);
          tail = tail.slice(sep + 2);
          let evt = "message";
          const dataLines: string[] = [];
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) evt = line.slice(6).trim();
            else if (line.startsWith("data:"))
              dataLines.push(line.slice(5).trimStart());
          }
          if (!dataLines.length) continue;
          const data = dataLines.join("\n");
          if (data === "[DONE]") continue;
          try {
            const obj = JSON.parse(data);
            if (evt.startsWith("hermes.tool")) {
              const idx = turnTools.findIndex((x) => x.id === obj.toolCallId);
              const entry: ToolEvent = {
                id: obj.toolCallId,
                tool: obj.tool,
                status: obj.status,
                label: obj.label,
              };
              if (idx === -1) turnTools.push(entry);
              else
                turnTools[idx] = {
                  ...turnTools[idx],
                  ...entry,
                  label: entry.label ?? turnTools[idx].label,
                };
              setTools([...turnTools]);
              if (stageRef.current !== "streaming") setStage("tools-active");
            } else if (typeof obj === "object" && obj !== null) {
              const delta = obj?.choices?.[0]?.delta?.content;
              if (typeof delta === "string") {
                assembled += delta;
                setStreaming(assembled);
                setStage("streaming");
              }
            }
          } catch {
            /* ignore non-JSON SSE */
          }
        }
      });

      if (assembled || turnTools.length) {
        setHistory([
          ...turn,
          {
            role: "assistant",
            content: assembled,
            tools: turnTools.length ? turnTools : undefined,
          },
        ]);
      }
      setStreaming("");
      setTools([]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setStage("idle");
      setStartedAt(null);
    }
  }, [input, pending, history]);

  const elapsed = startedAt ? Math.floor((now - startedAt) / 1000) : 0;
  const activeTool =
    tools.find((t) => t.status !== "completed") ?? tools[tools.length - 1];

  const clear = useCallback(() => {
    setHistory([]);
    setTools([]);
    setStreaming("");
    setErr(null);
  }, []);

  return {
    history,
    input,
    setInput,
    streaming,
    tools,
    stage,
    pending,
    err,
    elapsed,
    activeTool,
    send,
    clear,
  };
}
