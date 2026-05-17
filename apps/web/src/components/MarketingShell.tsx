"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import { theme } from "@/lib/theme";

/**
 * Top-nav + footer used across the public marketing surfaces (landing,
 * pricing, trust, docs). App-internal pages keep their sidebar AppShell.
 */
export function MarketingShell({ children, transparentNav }: {
  children: React.ReactNode;
  transparentNav?: boolean;
}) {
  return (
    <div style={{
      width: "100%", minHeight: "100vh",
      background: theme.bg, color: theme.ink,
      fontFamily: theme.body, display: "flex", flexDirection: "column",
    }}>
      <Nav transparent={transparentNav}/>
      <div style={{ flex: 1 }}>{children}</div>
      <Footer/>
    </div>
  );
}

function Nav({ transparent }: { transparent?: boolean }) {
  const path = usePathname() ?? "";
  const links = [
    { href: "/", label: "Product" },
    { href: "/pricing", label: "Pricing" },
    { href: "/docs", label: "Docs" },
    { href: "/trust", label: "Trust" },
  ];
  return (
    <nav style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "24px 56px",
      borderBottom: transparent ? "none" : `1px solid ${theme.hair}`,
      background: theme.bg,
      position: "sticky", top: 0, zIndex: 20,
    }}>
      <Link href="/" style={{
        display: "flex", alignItems: "center", gap: 12,
        textDecoration: "none", color: theme.ink,
      }}>
        <span style={{
          display: "inline-block", width: 28, height: 28,
          fontFamily: theme.display, fontWeight: 700, fontSize: 34,
          lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em",
        }}>a</span>
        <span style={{
          fontFamily: theme.body, fontWeight: 600, fontSize: 16,
          letterSpacing: "0.04em",
        }}>aki</span>
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.12em",
        }}>v 0.7 · beta</span>
      </Link>
      <div className="aki-nav-links" style={{
        display: "flex", gap: 28, alignItems: "center",
        fontFamily: theme.body, fontSize: 14, fontWeight: 500,
      }}>
        {links.map((l) => {
          const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
          return (
            <Link key={l.href} href={l.href} style={{
              color: active ? theme.ink : theme.inkDim,
              textDecoration: "none",
              borderBottom: active ? `1px solid ${theme.accent}` : "1px solid transparent",
              paddingBottom: 2,
            }}>{l.label}</Link>
          );
        })}
        <Show when="signed-out">
          <SignInButton mode="modal">
            <span style={{ color: theme.inkDim, cursor: "pointer" }}>Sign in</span>
          </SignInButton>
          <SignUpButton mode="modal">
            <button style={primaryPill}>Get on the beta</button>
          </SignUpButton>
        </Show>
        <Show when="signed-in">
          <Link href="/board" style={{ ...primaryPill, textDecoration: "none" }}>Open app</Link>
          <UserButton/>
        </Show>
      </div>
      <style>{`
        @media (max-width: 720px) {
          .aki-nav-links { gap: 16px; font-size: 13px; }
          .aki-nav-links > a { display: none; }
          .aki-nav-links > a[data-keep] { display: inline; }
        }
      `}</style>
    </nav>
  );
}

const primaryPill: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 13,
  padding: "9px 16px", borderRadius: 999, cursor: "pointer",
};

export function Footer() {
  const year = new Date().getFullYear();
  const groups: { label: string; links: { href: string; text: string; external?: boolean }[] }[] = [
    {
      label: "product",
      links: [
        { href: "/", text: "Overview" },
        { href: "/pricing", text: "Pricing" },
        { href: "/docs", text: "Docs" },
        { href: "/trust", text: "Trust & security" },
      ],
    },
    {
      label: "developers",
      links: [
        { href: "/docs/getting-started", text: "Getting started" },
        { href: "/docs/writing-a-brief", text: "Writing a brief" },
        { href: "/docs/connecting-tools", text: "Connecting tools" },
        { href: "/docs/audit", text: "Audit log" },
      ],
    },
    {
      label: "company",
      links: [
        { href: "https://status.aki.dev", text: "Status", external: true },
        { href: "https://github.com/anthropics", text: "GitHub", external: true },
        { href: "mailto:hello@tryclean.ai", text: "hello@tryclean.ai" },
        { href: "mailto:security@tryclean.ai", text: "Responsible disclosure" },
      ],
    },
  ];

  return (
    <footer style={{
      borderTop: `1px solid ${theme.hair}`,
      padding: "56px 56px 32px",
      marginTop: 80,
    }}>
      <div className="aki-footer-grid" style={{
        display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 40,
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{
              display: "inline-block", width: 28, height: 28,
              fontFamily: theme.display, fontWeight: 700, fontSize: 34,
              lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em",
            }}>a</span>
            <span style={{
              fontFamily: theme.body, fontWeight: 600, fontSize: 16,
              letterSpacing: "0.04em",
            }}>aki</span>
          </div>
          <div style={{
            marginTop: 16, fontFamily: theme.body, fontSize: 14,
            color: theme.inkDim, lineHeight: 1.55, maxWidth: 320,
          }}>
            Named agents your team can DM in Slack. Each one shows its work,
            cites its sources, and asks before it spends.
          </div>
        </div>
        {groups.map((g) => (
          <div key={g.label}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 16,
            }}>{g.label}</div>
            <ul style={{
              listStyle: "none", padding: 0, margin: 0,
              display: "flex", flexDirection: "column", gap: 10,
            }}>
              {g.links.map((l) => (
                <li key={l.text}>
                  {l.external || l.href.startsWith("mailto:") ? (
                    <a href={l.href} target={l.external ? "_blank" : undefined}
                       rel={l.external ? "noreferrer" : undefined}
                       style={footerLink}>{l.text}</a>
                  ) : (
                    <Link href={l.href} style={footerLink}>{l.text}</Link>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div style={{
        marginTop: 56, paddingTop: 24, borderTop: `1px solid ${theme.hair}`,
        display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap",
      }}>
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em",
        }}>© {year} aki labs · made with care</span>
        <span style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em",
        }}>v 0.7 · private beta</span>
      </div>
      <style>{`
        @media (max-width: 760px) {
          .aki-footer-grid { grid-template-columns: 1fr 1fr; }
        }
      `}</style>
    </footer>
  );
}

const footerLink: React.CSSProperties = {
  fontFamily: theme.body, fontSize: 14, color: theme.inkDim,
  textDecoration: "none",
};
