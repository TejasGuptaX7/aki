"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";
import { theme } from "@/lib/theme";

/**
 * Shared shell for /chat, /connect, /audit. 240px sidebar on the left,
 * scrollable main column on the right. Matches the Glyph II palette so
 * the app feels like a continuation of the landing, not a separate thing.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const nav = [
    { href: "/chat", label: "Chat" },
    { href: "/connect", label: "Connect" },
    { href: "/audit", label: "Audit" },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", minHeight: "100vh", background: theme.bg, color: theme.ink, fontFamily: theme.body }}>
      <aside style={{
        position: "sticky", top: 0, height: "100vh",
        borderRight: `1px solid ${theme.hair}`,
        padding: "24px 20px",
        display: "flex", flexDirection: "column", justifyContent: "space-between",
        background: theme.bg,
      }}>
        <div>
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: 12, textDecoration: "none", color: theme.ink, marginBottom: 40 }}>
            <span style={{ display: "inline-block", width: 28, height: 28, fontFamily: theme.display, fontWeight: 700, fontSize: 34, lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em" }}>a</span>
            <span style={{ fontFamily: theme.body, fontWeight: 600, fontSize: 16, letterSpacing: "0.04em" }}>aki</span>
            <span style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.12em", marginLeft: "auto" }}>v 0.7</span>
          </Link>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {nav.map((n) => {
              const active = path?.startsWith(n.href);
              return (
                <Link key={n.href} href={n.href} style={{
                  textDecoration: "none",
                  padding: "10px 12px",
                  borderRadius: 6,
                  fontFamily: theme.body, fontSize: 14, fontWeight: 500,
                  color: active ? theme.ink : theme.inkDim,
                  background: active ? "rgba(241,237,224,0.06)" : "transparent",
                  borderLeft: `2px solid ${active ? theme.accent : "transparent"}`,
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                }}>
                  <span>{n.label}</span>
                </Link>
              );
            })}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 8px" }}>
          <UserButton/>
          <span style={{ fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.16em", textTransform: "uppercase" }}>
            account
          </span>
        </div>
      </aside>

      <main style={{ overflowY: "auto", minHeight: "100vh" }}>
        {children}
      </main>
    </div>
  );
}

export function SectionHeader({ kicker, title, lede }: { kicker: string; title: React.ReactNode; lede?: React.ReactNode }) {
  return (
    <header style={{ padding: "48px 56px 32px", borderBottom: `1px solid ${theme.hair}` }}>
      <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 14 }}>
        {kicker}
      </div>
      <h1 style={{ margin: 0, fontFamily: theme.display, fontWeight: 600, fontSize: 48, lineHeight: 1.05, letterSpacing: "-0.025em" }}>
        {title}
      </h1>
      {lede && (
        <p style={{ margin: "16px 0 0", fontFamily: theme.body, fontSize: 16, color: theme.inkLede, lineHeight: 1.5, maxWidth: 620 }}>
          {lede}
        </p>
      )}
    </header>
  );
}

export function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ margin: "16px 56px", padding: "12px 18px", background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)", color: "#ee5959", fontFamily: theme.mono, fontSize: 12 }}>
      {children}
    </div>
  );
}
