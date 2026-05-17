import type { Metadata } from "next";
import Link from "next/link";
import { Show, SignUpButton } from "@clerk/nextjs";
import { theme } from "@/lib/theme";
import { MarketingShell } from "@/components/MarketingShell";

export const metadata: Metadata = {
  title: "Pricing — Aki",
  description: "Free during beta. Unlimited agents, all connectors, full audit history. Per-org pricing arrives when we charge — no surprise migrations.",
  openGraph: {
    title: "Aki — free during beta",
    description: "Spin up as many agents as you need while we're in beta.",
    type: "website",
  },
};

export default function PricingPage() {
  return (
    <MarketingShell>
      <Hero/>
      <WhatYouGet/>
      <WhatsComing/>
      <FAQ/>
      <BottomCTA/>
    </MarketingShell>
  );
}

function Hero() {
  return (
    <section style={{ padding: "60px 56px 40px", textAlign: "center" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint,
      }}>/01 · pricing</div>
      <h1 style={{
        margin: "18px 0 0", fontFamily: theme.display, fontWeight: 600,
        fontSize: 76, lineHeight: 1, letterSpacing: "-0.03em",
      }}>
        Free <span style={{ fontStyle: "italic", fontWeight: 500 }}>during beta.</span>
      </h1>
      <p style={{
        margin: "26px auto 0", fontFamily: theme.body, fontSize: 18,
        lineHeight: 1.55, color: theme.inkLede, maxWidth: 600,
      }}>
        One plan, everything unlocked. We&rsquo;ll start charging when the product is
        stable and the cost-to-serve is honest enough to defend a price tag.
      </p>
      <div style={{
        marginTop: 32, display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap",
      }}>
        <Show when="signed-out">
          <SignUpButton mode="modal" forceRedirectUrl="/onboarding">
            <button style={primaryCTA}>Get on the beta</button>
          </SignUpButton>
        </Show>
        <Show when="signed-in">
          <Link href="/onboarding" style={{ ...primaryCTA, textDecoration: "none" }}>
            Spin up an agent
          </Link>
        </Show>
      </div>
    </section>
  );
}

const primaryCTA: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 14,
  padding: "12px 24px", borderRadius: 999, cursor: "pointer",
};

function WhatYouGet() {
  const items = [
    {
      kicker: "agents",
      title: "Unlimited agents",
      body: "Spin up as many named agents as your team can name. Each gets its own brief, memory, and connections. No seat counting, no per-agent fees.",
    },
    {
      kicker: "connectors",
      title: "Every connector",
      body: "Gmail, Slack, Linear, Salesforce, Google Calendar, GitHub, Notion, Postgres, S3, Stripe — every connector we ship, on by default. Browser mode included for the long tail.",
    },
    {
      kicker: "receipts",
      title: "Full audit history",
      body: "Every tool call, every chat, every consent decision — hash-chained from row one. Export anytime. No retention cap during beta.",
    },
  ];
  return (
    <section style={{ padding: "40px 56px 60px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint, marginBottom: 24,
      }}>/02 · what you get</div>
      <div className="aki-pricing-grid" style={{
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18,
      }}>
        {items.map((i) => (
          <div key={i.kicker} style={{
            padding: "28px 28px", background: theme.bgSoft,
            border: `1px solid ${theme.hair}`,
            borderTop: `2px solid ${theme.accent}`,
            display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.accent,
              letterSpacing: "0.22em", textTransform: "uppercase",
            }}>{i.kicker}</div>
            <div style={{
              fontFamily: theme.display, fontWeight: 600, fontSize: 26,
              letterSpacing: "-0.02em", lineHeight: 1.15, color: theme.ink,
            }}>{i.title}</div>
            <div style={{
              fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
              lineHeight: 1.55,
            }}>{i.body}</div>
          </div>
        ))}
      </div>
      <style>{`@media (max-width: 900px) { .aki-pricing-grid { grid-template-columns: 1fr; } }`}</style>
    </section>
  );
}

function WhatsComing() {
  const items = [
    {
      kicker: "when we charge",
      title: "Per-org pricing",
      body: "One subscription per workspace, priced against how much real work the agents do for you — not against seat count. We'll publish the formula before we turn billing on.",
    },
    {
      kicker: "when we charge",
      title: "Usage caps you set",
      body: "You set the monthly model-spend ceiling. Past it, agents pause and ping you instead of running up an unbounded bill. The same ceiling protects you on day one of beta — it's just $0 today.",
    },
    {
      kicker: "when we charge",
      title: "Priority support",
      body: "Paid plans get a dedicated Slack channel with the team and a 24-hour SLA on bugs. Beta users get best-effort and very fast email — we read every message.",
    },
  ];
  return (
    <section style={{ padding: "0 56px 60px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint, marginBottom: 24,
      }}>/03 · what&rsquo;s coming</div>
      <h2 style={{
        margin: "0 0 24px", fontFamily: theme.display, fontWeight: 600,
        fontSize: 36, lineHeight: 1.1, letterSpacing: "-0.02em", maxWidth: 760,
      }}>
        Three things will change when we turn billing on.{" "}
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>None of them should surprise you.</span>
      </h2>
      <div className="aki-pricing-grid" style={{
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18,
      }}>
        {items.map((i) => (
          <div key={i.title} style={{
            padding: "24px 24px", background: "transparent",
            border: `1px dashed ${theme.hair}`,
            display: "flex", flexDirection: "column", gap: 12,
          }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.22em", textTransform: "uppercase",
            }}>{i.kicker}</div>
            <div style={{
              fontFamily: theme.display, fontWeight: 600, fontSize: 22,
              letterSpacing: "-0.015em", lineHeight: 1.2, color: theme.inkLede,
            }}>{i.title}</div>
            <div style={{
              fontFamily: theme.body, fontSize: 14, color: theme.inkDim,
              lineHeight: 1.55,
            }}>{i.body}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function FAQ() {
  const faqs: { q: string; a: React.ReactNode }[] = [
    {
      q: "What counts as a beta user?",
      a: "Anyone who signs up before we turn billing on, which we estimate at three to six months out. Beta users get a 60-day notice before any plan change kicks in, and we'll honor a transition discount for the first paid year.",
    },
    {
      q: "Who pays for the model calls?",
      a: "We do, during beta. When we start charging, model spend is metered separately and you set the ceiling. Today you get the full agent runtime — Anthropic Claude, OpenAI fallback — without thinking about token math.",
    },
    {
      q: "What if I hit a connector you don't have?",
      a: <>Browser mode handles anything with a web UI. If you need a deeper integration we don&apos;t ship yet, email <a href="mailto:hello@tryclean.ai" style={{ color: theme.accent }}>hello@tryclean.ai</a> — connector requests from beta users go to the top of our queue.</>,
    },
    {
      q: "Is there an enterprise plan?",
      a: <>Not yet. SAML SSO, data residency, and a signed BAA are on the v2 roadmap. If you need those today, get on the beta and tell us — it shifts our priorities.</>,
    },
  ];
  return (
    <section style={{ padding: "0 56px 80px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint, marginBottom: 24,
      }}>/04 · questions</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 760 }}>
        {faqs.map((f) => (
          <details key={f.q} style={{
            padding: "16px 20px", background: theme.bgSoft,
            border: `1px solid ${theme.hair}`,
          }}>
            <summary style={{
              cursor: "pointer", fontFamily: theme.display, fontSize: 18,
              fontWeight: 600, letterSpacing: "-0.01em", color: theme.ink,
              listStyle: "none",
            }}>{f.q}</summary>
            <div style={{
              marginTop: 12, fontFamily: theme.body, fontSize: 15,
              color: theme.inkLede, lineHeight: 1.6,
            }}>{f.a}</div>
          </details>
        ))}
      </div>
    </section>
  );
}

function BottomCTA() {
  return (
    <section style={{
      margin: "0 56px 24px", padding: "48px 40px",
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      textAlign: "center",
    }}>
      <h2 style={{
        margin: 0, fontFamily: theme.display, fontWeight: 600,
        fontSize: 36, lineHeight: 1.1, letterSpacing: "-0.02em",
      }}>
        Ready to put an agent to work?
      </h2>
      <div style={{ marginTop: 24 }}>
        <Show when="signed-out">
          <SignUpButton mode="modal" forceRedirectUrl="/onboarding">
            <button style={primaryCTA}>Get on the beta</button>
          </SignUpButton>
        </Show>
        <Show when="signed-in">
          <Link href="/onboarding" style={{ ...primaryCTA, textDecoration: "none" }}>
            Spin up an agent
          </Link>
        </Show>
      </div>
    </section>
  );
}
