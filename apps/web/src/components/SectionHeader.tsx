"use client"

import { theme } from "@/theme"

interface SectionHeaderProps {
  kicker: string
  title: string
  subtitle?: string
}

export default function SectionHeader({ kicker, title, subtitle }: SectionHeaderProps) {
  return (
    <div style={{ marginBottom: 32 }}>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.22em",
          color: theme.inkFaint,
          marginBottom: 8,
        }}
      >
        {kicker}
      </div>
      <h1
        style={{
          fontFamily: theme.display,
          fontSize: 32,
          fontWeight: 400,
          color: theme.ink,
          margin: 0,
          lineHeight: 1.2,
        }}
      >
        {title}
      </h1>
      {subtitle && (
        <p
          style={{
            fontFamily: theme.body,
            fontSize: 14,
            color: theme.inkDim,
            marginTop: 8,
            lineHeight: 1.5,
          }}
        >
          {subtitle}
        </p>
      )}
    </div>
  )
}
