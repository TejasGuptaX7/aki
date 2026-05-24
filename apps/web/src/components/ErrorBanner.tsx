"use client"

import { AlertTriangle } from "lucide-react"
import { theme } from "@/theme"

interface ErrorBannerProps {
  message: string
  onRetry?: () => void
}

export default function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div
      style={{
        background: "rgba(239,68,68,0.12)",
        border: "1px solid rgba(239,68,68,0.3)",
        borderRadius: 8,
        padding: 16,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <AlertTriangle size={20} color="#ef4444" />
      <span
        style={{
          fontFamily: theme.body,
          fontSize: 14,
          color: "#ef4444",
          flex: 1,
        }}
      >
        {message}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            background: "transparent",
            border: "1px solid #ef4444",
            color: "#ef4444",
            borderRadius: 999,
            padding: "4px 16px",
            fontFamily: theme.mono,
            fontSize: 12,
            cursor: "pointer",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "rgba(239,68,68,0.1)"
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent"
          }}
        >
          Retry
        </button>
      )}
    </div>
  )
}
