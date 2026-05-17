"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { theme } from "@/lib/theme";

export const docsNav: { href: string; label: string; group: string }[] = [
  { href: "/docs", label: "Overview", group: "start" },
  { href: "/docs/getting-started", label: "Getting started", group: "start" },
  { href: "/docs/writing-a-brief", label: "Writing a brief", group: "agents" },
  { href: "/docs/connecting-tools", label: "Connecting tools", group: "agents" },
  { href: "/docs/consent", label: "Consent tiers", group: "agents" },
  { href: "/docs/slack", label: "Slack", group: "channels" },
  { href: "/docs/audit", label: "Audit log", group: "operate" },
  { href: "/docs/troubleshooting", label: "Troubleshooting", group: "operate" },
];

const groupLabels: Record<string, string> = {
  start: "start here",
  agents: "agents",
  channels: "channels",
  operate: "operate",
};

export function DocsShell({ children, title, description }: {
  children: React.ReactNode;
  title?: string;
  description?: string;
}) {
  const path = usePathname() ?? "";

  const grouped = React.useMemo(() => {
    const m = new Map<string, typeof docsNav>();
    for (const item of docsNav) {
      const list = m.get(item.group) ?? [];
      list.push(item);
      m.set(item.group, list);
    }
    return Array.from(m.entries());
  }, []);

  return (
    <div className="aki-docs-shell" style={{
      display: "grid", gridTemplateColumns: "240px 1fr",
      gap: 0, maxWidth: 1240, margin: "0 auto", padding: "40px 32px",
    }}>
      <aside style={{
        position: "sticky", top: 90, alignSelf: "start",
        height: "calc(100vh - 120px)", overflowY: "auto",
        paddingRight: 24, borderRight: `1px solid ${theme.hair}`,
      }}>
        {grouped.map(([group, items]) => (
          <div key={group} style={{ marginBottom: 22 }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 10,
            }}>{groupLabels[group] ?? group}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {items.map((item) => {
                const active = path === item.href;
                return (
                  <Link key={item.href} href={item.href} style={{
                    padding: "6px 10px", borderRadius: 4,
                    fontFamily: theme.body, fontSize: 14,
                    color: active ? theme.ink : theme.inkDim,
                    background: active ? "rgba(241,237,224,0.05)" : "transparent",
                    borderLeft: `2px solid ${active ? theme.accent : "transparent"}`,
                    textDecoration: "none",
                  }}>{item.label}</Link>
                );
              })}
            </div>
          </div>
        ))}
      </aside>

      <main style={{ paddingLeft: 40, maxWidth: 760, minWidth: 0 }}>
        {title && (
          <header style={{ marginBottom: 32 }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
              letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 12,
            }}>docs</div>
            <h1 style={{
              margin: 0, fontFamily: theme.display, fontWeight: 600,
              fontSize: 44, lineHeight: 1.05, letterSpacing: "-0.025em",
              color: theme.ink,
            }}>{title}</h1>
            {description && (
              <p style={{
                margin: "14px 0 0", fontFamily: theme.body, fontSize: 17,
                lineHeight: 1.55, color: theme.inkLede, maxWidth: 640,
              }}>{description}</p>
            )}
          </header>
        )}
        <div>{children}</div>
        <DocsPagination path={path}/>
      </main>

      <style>{`
        @media (max-width: 880px) {
          .aki-docs-shell { grid-template-columns: 1fr !important; }
          .aki-docs-shell > aside {
            position: static !important;
            height: auto !important;
            border-right: none !important;
            border-bottom: 1px solid ${theme.hair} !important;
            padding-bottom: 24px;
            margin-bottom: 24px;
            padding-right: 0 !important;
          }
          .aki-docs-shell > main { padding-left: 0 !important; }
        }
      `}</style>
    </div>
  );
}

function DocsPagination({ path }: { path: string }) {
  const idx = docsNav.findIndex((i) => i.href === path);
  const prev = idx > 0 ? docsNav[idx - 1] : null;
  const next = idx >= 0 && idx < docsNav.length - 1 ? docsNav[idx + 1] : null;
  if (!prev && !next) return null;
  return (
    <nav style={{
      marginTop: 56, paddingTop: 24, borderTop: `1px solid ${theme.hair}`,
      display: "flex", justifyContent: "space-between", gap: 16,
    }}>
      {prev ? (
        <Link href={prev.href} style={pagBtn}>
          <span style={{ display: "block", fontSize: 10, color: theme.inkFaint, letterSpacing: "0.2em", textTransform: "uppercase" }}>previous</span>
          <span style={{ display: "block", marginTop: 4, color: theme.ink, fontWeight: 500 }}>{prev.label}</span>
        </Link>
      ) : <span/>}
      {next ? (
        <Link href={next.href} style={{ ...pagBtn, textAlign: "right" }}>
          <span style={{ display: "block", fontSize: 10, color: theme.inkFaint, letterSpacing: "0.2em", textTransform: "uppercase" }}>next</span>
          <span style={{ display: "block", marginTop: 4, color: theme.accent, fontWeight: 500 }}>{next.label} →</span>
        </Link>
      ) : <span/>}
    </nav>
  );
}

const pagBtn: React.CSSProperties = {
  flex: 1, maxWidth: 280,
  padding: "12px 16px", border: `1px solid ${theme.hair}`, borderRadius: 4,
  fontFamily: theme.body, fontSize: 14, textDecoration: "none", color: theme.ink,
};
