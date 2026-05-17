"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";
import { theme } from "@/lib/theme";
import { useAgents, pickDefaultAgent } from "@/lib/agents";
import { approvalsApi } from "@/lib/api";
import { useAuth } from "@clerk/nextjs";
import { ErrorBoundary } from "./ErrorBoundary";

/**
 * App-wide chrome: 240px sidebar + scrolling main column.
 * Sidebar lists named agents (each tenant runs many) and the global
 * sections — Connect, Audit, Approvals.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname() ?? "";
  const { agents, status } = useAgents();
  const currentAgentId = extractAgentIdFromPath(path);
  const approvalsCount = useApprovalsCount();

  const sections = [
    { href: "/board", label: "Board" },
    { href: "/agents", label: "Agents" },
    { href: "/connect", label: "Connect" },
    { href: "/audit", label: "Audit" },
    { href: "/approvals", label: "Approvals", badge: approvalsCount },
  ];

  const activeAgents = agents.filter((a) => a.status === "active");

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "260px 1fr",
      minHeight: "100vh", background: theme.bg, color: theme.ink, fontFamily: theme.body,
    }}>
      <aside style={{
        position: "sticky", top: 0, height: "100vh",
        borderRight: `1px solid ${theme.hair}`,
        padding: "24px 16px 16px 20px",
        display: "flex", flexDirection: "column",
        background: theme.bg, gap: 16, overflowY: "auto",
      }}>
        <Link href="/" style={{
          display: "flex", alignItems: "center", gap: 12,
          textDecoration: "none", color: theme.ink, marginBottom: 8,
        }}>
          <span style={{
            display: "inline-block", width: 28, height: 28,
            fontFamily: theme.display, fontWeight: 700, fontSize: 34,
            lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em",
          }}>a</span>
          <span style={{ fontFamily: theme.body, fontWeight: 600, fontSize: 16, letterSpacing: "0.04em" }}>aki</span>
          <span style={{
            fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
            letterSpacing: "0.12em", marginLeft: "auto",
          }}>v 0.7</span>
        </Link>

        {/* Agents */}
        <div>
          <SidebarLabel>agents</SidebarLabel>
          {status === "loading" ? (
            <div style={{ padding: "6px 12px", fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
              loading…
            </div>
          ) : activeAgents.length === 0 ? (
            <Link href="/onboarding" style={sidebarRowStyle(false)}>
              <span style={{ color: theme.inkDim, fontStyle: "italic" }}>create your first</span>
            </Link>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {activeAgents.map((a) => {
                const active = a.id === currentAgentId;
                return (
                  <Link key={a.id} href={`/chat/${a.id}`} style={sidebarRowStyle(active)}>
                    <span style={{
                      width: 6, height: 6, borderRadius: "50%",
                      background: active ? theme.accent : theme.inkFaint,
                      flexShrink: 0,
                    }}/>
                    <span style={{
                      flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>{a.name}</span>
                  </Link>
                );
              })}
            </div>
          )}
          <Link href="/agents" style={{
            display: "block", marginTop: 6,
            padding: "8px 12px", borderRadius: 6,
            fontFamily: theme.body, fontSize: 13, color: theme.inkDim,
            border: `1px dashed ${theme.hair}`,
            textDecoration: "none", textAlign: "center",
          }}>+ New agent</Link>
        </div>

        {/* Sections */}
        <div>
          <SidebarLabel>workspace</SidebarLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {sections.map((s) => {
              const active = path.startsWith(s.href);
              return (
                <Link key={s.href} href={s.href} style={sidebarRowStyle(active)}>
                  <span style={{ flex: 1 }}>{s.label}</span>
                  {typeof s.badge === "number" && s.badge > 0 && (
                    <span style={{
                      fontFamily: theme.mono, fontSize: 10,
                      background: theme.accent, color: theme.bg,
                      padding: "1px 6px", borderRadius: 999, fontWeight: 600,
                    }}>{s.badge}</span>
                  )}
                </Link>
              );
            })}
          </div>
        </div>

        <div style={{ flex: 1 }}/>

        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 8px", borderTop: `1px solid ${theme.hair}`,
        }}>
          <UserButton/>
          <span style={{
            fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
            letterSpacing: "0.16em", textTransform: "uppercase",
          }}>account</span>
        </div>
      </aside>

      <main style={{ overflowY: "auto", minHeight: "100vh" }}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  );
}

function sidebarRowStyle(active: boolean): React.CSSProperties {
  return {
    textDecoration: "none",
    padding: "8px 12px",
    borderRadius: 6,
    fontFamily: theme.body, fontSize: 13, fontWeight: 500,
    color: active ? theme.ink : theme.inkDim,
    background: active ? "rgba(241,237,224,0.06)" : "transparent",
    borderLeft: `2px solid ${active ? theme.accent : "transparent"}`,
    display: "flex", alignItems: "center", gap: 10,
  };
}

function SidebarLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
      letterSpacing: "0.22em", textTransform: "uppercase",
      padding: "0 12px 8px", marginTop: 4,
    }}>{children}</div>
  );
}

function extractAgentIdFromPath(path: string): string | null {
  // /chat/{id} or /chat/{id}/... → id
  const m = path.match(/^\/chat\/([^/]+)/);
  return m ? m[1] : null;
}

function useApprovalsCount(): number {
  const { getToken, isSignedIn } = useAuth();
  const [count, setCount] = React.useState(0);
  React.useEffect(() => {
    if (!isSignedIn) return;
    let mounted = true;
    const tick = async () => {
      try {
        const items = await approvalsApi.list(() => getToken({ template: "aki" }));
        if (mounted) setCount(items.length);
      } catch {
        /* ignore — endpoint may not exist yet */
      }
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => { mounted = false; clearInterval(id); };
  }, [getToken, isSignedIn]);
  return count;
}

export function SectionHeader({ kicker, title, lede, right }: {
  kicker: string; title: React.ReactNode; lede?: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <header style={{
      padding: "48px 56px 32px", borderBottom: `1px solid ${theme.hair}`,
      display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 24,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
          textTransform: "uppercase", color: theme.inkFaint, marginBottom: 14,
        }}>{kicker}</div>
        <h1 style={{
          margin: 0, fontFamily: theme.display, fontWeight: 600,
          fontSize: 48, lineHeight: 1.05, letterSpacing: "-0.025em",
        }}>{title}</h1>
        {lede && (
          <p style={{
            margin: "16px 0 0", fontFamily: theme.body, fontSize: 16,
            color: theme.inkLede, lineHeight: 1.5, maxWidth: 620,
          }}>{lede}</p>
        )}
      </div>
      {right}
    </header>
  );
}

export function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      margin: "16px 56px", padding: "12px 18px",
      background: "rgba(238,89,89,0.10)", border: "1px solid rgba(238,89,89,0.32)",
      color: "#ee5959", fontFamily: theme.mono, fontSize: 12,
    }}>{children}</div>
  );
}

export { pickDefaultAgent };
