"use client"

import { theme } from "@/theme"

type Status = "queued" | "running" | "done" | "failed" | "cancelled" | "pending" | "active" | "disabled"

const styles: Record<string, React.CSSProperties> = {
  queued: {
    background: "rgba(241,237,224,0.06)",
    color: theme.inkDim,
    border: "1px solid " + theme.hair,
  },
  running: {
    background: theme.accentDim,
    color: theme.accent,
    border: "1px solid rgba(197,236,79,0.3)",
    animation: "pulse 1.5s ease-in-out infinite",
  },
  done: {
    background: "rgba(34,197,94,0.12)",
    color: "#22c55e",
    border: "1px solid rgba(34,197,94,0.3)",
  },
  failed: {
    background: "rgba(239,68,68,0.12)",
    color: "#ef4444",
    border: "1px solid rgba(239,68,68,0.3)",
  },
  cancelled: {
    background: "rgba(234,179,8,0.12)",
    color: "#eab308",
    border: "1px solid rgba(234,179,8,0.3)",
  },
  pending: {
    background: "rgba(234,179,8,0.12)",
    color: "#eab308",
    border: "1px solid rgba(234,179,8,0.3)",
  },
  active: {
    background: theme.accentDim,
    color: theme.accent,
    border: "1px solid rgba(197,236,79,0.3)",
  },
  disabled: {
    background: "rgba(241,237,224,0.06)",
    color: theme.inkFaint,
    border: "1px solid " + theme.hair,
  },
}

interface StatusBadgeProps {
  status: Status
  label?: string
}

export default function StatusBadge({ status, label }: StatusBadgeProps) {
  const displayLabel = label || status
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        padding: "2px 10px",
        fontFamily: theme.mono,
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        ...styles[status],
      }}
    >
      {displayLabel}
    </span>
  )
}
