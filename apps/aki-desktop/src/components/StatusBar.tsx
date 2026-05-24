import { theme } from "../lib/theme";
import type { Stage, ToolEvent } from "../hooks/useChat";

export function StatusBar({
  stage,
  elapsed,
  activeTool,
  toolCount,
}: {
  stage: Stage;
  elapsed: number;
  activeTool?: ToolEvent;
  toolCount: number;
}) {
  const { headline, sub } = describe(stage, elapsed, activeTool, toolCount);
  return (
    <div
      style={{
        marginBottom: 24,
        padding: "14px 18px",
        background: theme.bgSoft,
        border: `1px solid ${theme.hair}`,
        borderLeft: `2px solid ${theme.accent}`,
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <Pulse />
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontFamily: theme.body,
            fontSize: 14,
            fontWeight: 500,
            color: theme.ink,
          }}
        >
          {headline}
        </div>
        {sub && (
          <div
            style={{
              marginTop: 4,
              fontFamily: theme.mono,
              fontSize: 11,
              color: theme.inkDim,
              wordBreak: "break-all",
            }}
          >
            {sub}
          </div>
        )}
      </div>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 11,
          color: theme.inkFaint,
          letterSpacing: "0.18em",
        }}
      >
        {elapsed}s
      </div>
    </div>
  );
}

function describe(
  stage: Stage,
  elapsed: number,
  activeTool: ToolEvent | undefined,
  toolCount: number
): { headline: string; sub?: string } {
  if (stage === "connecting") return { headline: "Connecting to Aki…" };
  if (stage === "waking")
    return {
      headline: "Waking up your agent…",
      sub:
        elapsed > 8
          ? "first chat in 15+ minutes spins up a fresh container (~10s)"
          : "this happens after idle periods",
    };
  if (stage === "thinking") return { headline: "Thinking…" };
  if (stage === "tools-active") {
    return {
      headline: activeTool
        ? `Running ${activeTool.tool}…`
        : "Calling tools…",
      sub:
        activeTool?.label ||
        (toolCount > 1 ? `${toolCount} tool calls so far` : undefined),
    };
  }
  if (stage === "streaming") return { headline: "Streaming reply…" };
  return { headline: "Working…" };
}

function Pulse() {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: theme.accent,
        animation: "akiPulse 1.4s ease-in-out infinite",
      }}
    />
  );
}
