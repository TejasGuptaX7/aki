import { useState } from "react";
import { theme } from "../lib/theme";
import type { ToolEvent } from "../hooks/useChat";

export function ToolPanel({ tools }: { tools: ToolEvent[] }) {
  const [open, setOpen] = useState(true);

  const grouped: Record<string, ToolEvent> = {};
  for (const t of tools) {
    grouped[t.id] = { ...grouped[t.id], ...t, label: t.label ?? grouped[t.id]?.label };
  }
  const rows = Object.values(grouped);

  return (
    <div
      style={{
        marginTop: 12,
        padding: "12px 16px",
        background: "rgba(197,236,79,0.04)",
        border: `1px solid ${theme.accentDim}`,
        borderRadius: 4,
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: "transparent",
          border: "none",
          padding: 0,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
        }}
      >
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 10,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: theme.accent,
          }}
        >
          tools · {rows.length}
        </span>
        <span style={{ color: theme.inkFaint, fontSize: 10, marginLeft: "auto" }}>
          {open ? "▼" : "▶"}
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 10 }}>
          {rows.map((t) => (
            <div
              key={t.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 12,
                marginBottom: 6,
                fontFamily: theme.mono,
                fontSize: 12,
                color: theme.inkLede,
              }}
            >
              <span
                style={{
                  color:
                    t.status === "completed" ? theme.accent : theme.inkDim,
                  fontSize: 10,
                  lineHeight: "20px",
                }}
              >
                {t.status === "completed" ? "●" : "◌"}
              </span>
              <span style={{ minWidth: 180, color: theme.ink, flexShrink: 0 }}>
                {t.tool}
              </span>
              {t.label && (
                <span
                  title={t.label}
                  style={{
                    color: theme.inkDim,
                    fontSize: 11,
                    flex: 1,
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {t.label}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
