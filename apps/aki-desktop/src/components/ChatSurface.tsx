import { useRef, useEffect } from "react";
import { theme } from "../lib/theme";
import { EmptyChat } from "./EmptyChat";
import { MessageBlock } from "./MessageBlock";
import { StatusBar } from "./StatusBar";
import { ToolPanel } from "./ToolPanel";
import type { Msg, Stage, ToolEvent } from "../hooks/useChat";

export function ChatSurface({
  history,
  streaming,
  tools,
  stage,
  pending,
  elapsed,
  activeTool,
  onPickExample,
}: {
  history: Msg[];
  streaming: string;
  tools: ToolEvent[];
  stage: Stage;
  pending: boolean;
  elapsed: number;
  activeTool?: ToolEvent;
  onPickExample: (text: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, streaming, tools, stage]);

  const streamingMsg: Msg = {
    role: "assistant",
    content: streaming,
    tools: tools.length ? tools : undefined,
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "40px 0" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 32px" }}>
        {history.length === 0 && stage === "idle" && (
          <EmptyChat onPick={onPickExample} />
        )}

        {history.map((m, i) => (
          <MessageBlock key={i} msg={m} />
        ))}

        {pending && (
          <StatusBar
            stage={stage}
            elapsed={elapsed}
            activeTool={activeTool}
            toolCount={tools.length}
          />
        )}

        {streaming && <MessageBlock msg={streamingMsg} />}

        <div ref={endRef} />
      </div>
    </div>
  );
}
