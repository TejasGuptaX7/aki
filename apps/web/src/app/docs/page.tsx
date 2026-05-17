import type { Metadata } from "next";
import Link from "next/link";
import { theme } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Docs — Aki",
  description: "How to write a brief, connect tools, work in Slack, read the audit log, and troubleshoot the common stuff.",
};

const sections: { href: string; title: string; blurb: string }[] = [
  { href: "/docs/getting-started", title: "Getting started", blurb: "Sign up to first running agent in five minutes." },
  { href: "/docs/writing-a-brief", title: "Writing a brief", blurb: "How to write a system prompt that survives contact with reality. Three worked examples." },
  { href: "/docs/connecting-tools", title: "Connecting tools", blurb: "OAuth walkthrough. Per-agent vs org-wide scoping. The catalog as of today." },
  { href: "/docs/consent", title: "Consent tiers", blurb: "Auto / ask / never-money. What triggers each. How to approve from Slack or web." },
  { href: "/docs/slack", title: "Slack", blurb: "Installing the bot. Mentioning specific agents. Long-task pingbacks." },
  { href: "/docs/audit", title: "Audit log", blurb: "What we record. The hash chain. How to verify locally." },
  { href: "/docs/troubleshooting", title: "Troubleshooting", blurb: "Top ten things that go wrong, with fixes." },
];

export default function DocsIndex() {
  return (
    <>
      <header style={{ marginBottom: 36 }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 12,
        }}>docs</div>
        <h1 style={{
          margin: 0, fontFamily: theme.display, fontWeight: 600,
          fontSize: 52, lineHeight: 1.05, letterSpacing: "-0.025em",
          color: theme.ink,
        }}>
          Everything you need.{" "}
          <span style={{ fontStyle: "italic", fontWeight: 500 }}>Nothing you don&rsquo;t.</span>
        </h1>
        <p style={{
          margin: "16px 0 0", fontFamily: theme.body, fontSize: 17,
          lineHeight: 1.55, color: theme.inkLede, maxWidth: 640,
        }}>
          Eight pages. Read them in order or jump straight to what&rsquo;s biting you
          today. If you can&rsquo;t find what you need,{" "}
          <a href="mailto:hello@tryclean.ai" style={{ color: theme.accent }}>email us</a> —
          we read every message.
        </p>
      </header>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {sections.map((s) => (
          <Link key={s.href} href={s.href} style={{
            padding: "20px 22px", background: theme.bgSoft,
            border: `1px solid ${theme.hair}`, textDecoration: "none",
            display: "block",
          }}>
            <div style={{
              fontFamily: theme.display, fontWeight: 600, fontSize: 22,
              letterSpacing: "-0.015em", color: theme.ink, marginBottom: 6,
            }}>{s.title}</div>
            <div style={{
              fontFamily: theme.body, fontSize: 14,
              color: theme.inkDim, lineHeight: 1.5,
            }}>{s.blurb}</div>
          </Link>
        ))}
      </div>
    </>
  );
}
