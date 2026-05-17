"use client";

import * as React from "react";
import Link from "next/link";
import { theme } from "@/lib/theme";

/**
 * Shared tab bar for /agents/[id] and its sub-routes. Keeps the active
 * underline + monospaced kicker consistent without forcing a layout
 * refactor (each page still owns its AppShell wrapper).
 */
export function AgentTabNav({ agentId, current }: {
  agentId: string;
  current: "detail" | "brain";
}) {
  const tabs = [
    { key: "detail", href: `/agents/${agentId}`, label: "Detail" },
    { key: "brain", href: `/agents/${agentId}/brain`, label: "Brain" },
  ] as const;
  return (
    <div style={{
      display: "flex", gap: 4, padding: "0 56px",
      borderBottom: `1px solid ${theme.hair}`,
    }}>
      {tabs.map((t) => {
        const active = t.key === current;
        return (
          <Link key={t.key} href={t.href} style={{
            padding: "12px 18px",
            fontFamily: theme.body, fontSize: 13, fontWeight: 500,
            color: active ? theme.ink : theme.inkDim,
            textDecoration: "none",
            borderBottom: `2px solid ${active ? theme.accent : "transparent"}`,
            marginBottom: -1,
          }}>{t.label}</Link>
        );
      })}
    </div>
  );
}
