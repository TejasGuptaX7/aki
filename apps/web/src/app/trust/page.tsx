import type { Metadata } from "next";
import * as React from "react";
import { theme } from "@/lib/theme";
import { MarketingShell } from "@/components/MarketingShell";

export const metadata: Metadata = {
  title: "Trust & security — Aki",
  description: "Per-org sandboxes, per-agent process isolation, hash-chained audit, three-tier consent. Honest about what we have shipped and what's still on the roadmap.",
  openGraph: {
    title: "Aki — trust & security",
    description: "What we have shipped, what's still in progress, who to email about disclosures.",
    type: "website",
  },
};

export default function TrustPage() {
  return (
    <MarketingShell>
      <Hero/>
      <Shipped/>
      <DataHandling/>
      <NotYet/>
      <Disclosure/>
    </MarketingShell>
  );
}

function Hero() {
  return (
    <section style={{ padding: "60px 56px 40px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint,
      }}>/00 · trust</div>
      <h1 style={{
        margin: "18px 0 0", fontFamily: theme.display, fontWeight: 600,
        fontSize: 64, lineHeight: 1, letterSpacing: "-0.025em", maxWidth: 920,
      }}>
        What we&rsquo;ve shipped.{" "}
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>
          What we haven&rsquo;t. Who to email.
        </span>
      </h1>
      <p style={{
        margin: "22px 0 0", fontFamily: theme.body, fontSize: 17,
        lineHeight: 1.6, color: theme.inkLede, maxWidth: 720,
      }}>
        This page is read by security buyers. Lying breaks deals, so
        we don&rsquo;t. Everything below is true today. Anything on the roadmap
        is labeled as such, with a real timeline where we know it.
      </p>
    </section>
  );
}

function Shipped() {
  const items: { kicker: string; title: string; body: React.ReactNode }[] = [
    {
      kicker: "isolation · L1",
      title: "Per-org gVisor-sandboxed container",
      body: <>Every customer runs in its own container under <a href="https://gvisor.dev" target="_blank" rel="noreferrer" style={link}>gVisor</a>, a userspace kernel from Google that intercepts system calls. A bug in our application code or in the agent runtime can&apos;t escape into the host. We rebuild the container image weekly and rotate base images on every CVE that matters.</>,
    },
    {
      kicker: "isolation · L2",
      title: "Per-agent OS process",
      body: <>Inside each customer&apos;s container, every named agent runs in its own OS process with its own file descriptors and its own memory. Cross-agent leaks within a single org would require kernel escape — the gVisor layer already covers that.</>,
    },
    {
      kicker: "data · L1",
      title: "Postgres row-level security",
      body: <>Belt and suspenders. Even if an agent process somehow read another org&apos;s rows from the database, Postgres&apos; row-level security policies block the query at the DB layer. Every table that holds tenant data has an org_id column and an RLS policy keyed on the connection&apos;s session variable. We test this on every migration.</>,
    },
    {
      kicker: "audit",
      title: "Hash-chained event log",
      body: <>Every tool call, chat message, and consent decision lands in an append-only Postgres table with a <code style={code}>content_hash</code> + <code style={code}>prev_hash</code>. You can verify the chain locally — we ship a small CLI that re-derives every hash and tells you if anything was retroactively altered. Append-only is enforced at the database level (no UPDATE or DELETE privileges on the role the API uses).</>,
    },
    {
      kicker: "consent",
      title: "Three-tier consent (the money rule)",
      body: <>Every tool call is classified into one of three tiers. <b style={{ color: theme.ink }}>Auto</b> runs without asking (read-only, internal-only). <b style={{ color: theme.ink }}>Ask</b> waits for a human nod (sending email outside the team, editing records, scheduling meetings). <b style={{ color: theme.ink }}>Never-money</b> always asks, full stop — and is the only tier for tool calls that spend money or trigger irreversible side effects. You can promote a tool into a stricter tier; you can never demote it past safe defaults.</>,
    },
    {
      kicker: "transport · L1",
      title: "TLS everywhere",
      body: <>HTTPS to the app, TLS to Postgres (Neon), TLS to S3-compatible storage (R2), TLS to every model provider. No plaintext on any wire we control. HSTS preload on the marketing domain.</>,
    },
    {
      kicker: "storage · L1",
      title: "Encryption at rest",
      body: <>Postgres data on Neon — AES-256 at rest, customer-managed key option on enterprise. Object storage on Cloudflare R2 — AES-256 at rest. OAuth tokens and connector secrets are envelope-encrypted with a per-org KEK before they ever touch the database.</>,
    },
    {
      kicker: "auth",
      title: "Clerk for identity, scoped session tokens",
      body: <>We don&apos;t store passwords. Authentication is delegated to Clerk; session tokens are short-lived JWTs scoped to a single org. MFA is supported today via Clerk; we&apos;ll surface it as a per-org enforcement toggle before GA.</>,
    },
  ];

  return (
    <section style={{ padding: "20px 56px 60px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.accent, marginBottom: 16,
      }}>/01 · shipped today</div>
      <div className="aki-trust-grid" style={{
        display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 18,
      }}>
        {items.map((i) => (
          <div key={i.title} style={{
            padding: "24px 26px", background: theme.bgSoft,
            border: `1px solid ${theme.hair}`,
            borderLeft: `2px solid ${theme.accent}`,
            display: "flex", flexDirection: "column", gap: 12,
          }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.accent,
              letterSpacing: "0.22em", textTransform: "uppercase",
            }}>{i.kicker}</div>
            <div style={{
              fontFamily: theme.display, fontWeight: 600, fontSize: 22,
              letterSpacing: "-0.015em", lineHeight: 1.2, color: theme.ink,
            }}>{i.title}</div>
            <div style={{
              fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
              lineHeight: 1.6,
            }}>{i.body}</div>
          </div>
        ))}
      </div>
      <style>{`@media (max-width: 900px) { .aki-trust-grid { grid-template-columns: 1fr; } }`}</style>
    </section>
  );
}

function DataHandling() {
  return (
    <section style={{ padding: "0 56px 60px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.accent, marginBottom: 16,
      }}>/02 · data handling</div>
      <div style={{
        padding: "26px 28px", background: theme.bgSoft,
        border: `1px solid ${theme.hair}`,
      }}>
        <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 18 }} className="aki-data-grid">
          {[
            ["Customer data", "Stored in our control plane (Neon, US-east). Never used to train models — your prompts and tool outputs are not part of any training set, ours or our providers'."],
            ["Model providers", "Anthropic Claude is primary. OpenAI is the structured-output fallback for select internal calls. Both are configured zero-retention where they support it. We don't ship customer data to any other AI provider."],
            ["Connector tokens", "Per-org envelope encryption with KEKs we rotate quarterly. The DEK never leaves the running process. Revocation is a single API call from /connect."],
            ["Backups", "Neon point-in-time recovery, 30-day retention. R2 versioning, 30-day retention. Audit chain is append-only — no backup needed for tamper detection."],
            ["Deletion", "On account deletion, we hard-delete from primary storage within 7 days and from backups within the retention window. Audit rows are anonymized (org_id replaced with a tombstone) but not deleted, since the hash chain must remain verifiable."],
            ["Sub-processors", "Neon (database), Cloudflare R2 (object storage), Clerk (auth), Anthropic + OpenAI (models), Composio (some connector OAuth flows). We'll publish a versioned sub-processor list before GA."],
          ].map(([k, v]) => (
            <React.Fragment key={k}>
              <div style={{
                fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
                letterSpacing: "0.14em", paddingTop: 4,
              }}>{k}</div>
              <div style={{
                fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
                lineHeight: 1.6,
              }}>{v}</div>
            </React.Fragment>
          ))}
        </div>
        <style>{`@media (max-width: 720px) { .aki-data-grid { grid-template-columns: 1fr !important; gap: 4px !important; } .aki-data-grid > div:nth-child(odd) { padding-top: 16px !important; } }`}</style>
      </div>
    </section>
  );
}

function NotYet() {
  const items = [
    {
      title: "SOC 2 Type II",
      status: "in progress",
      body: "We've engaged an auditor (Drata-based stack). Type I report expected Q3 2026; Type II 12 months after that. Pre-audit gap analysis is complete — no surprises. We'll publish the executive summary on request once the report is in hand.",
    },
    {
      title: "SAML SSO + SCIM",
      status: "v2 · coming",
      body: "Today we use Clerk for identity (Google / Microsoft / GitHub / email). SAML SSO and SCIM user provisioning are on the v2 enterprise roadmap. If you need them to evaluate Aki today, email us — we'll prioritize.",
    },
    {
      title: "Data residency",
      status: "v2 · coming",
      body: "All data is in US-east today (Neon's primary region). EU residency is on the v2 roadmap and we'll do it the right way (separate Neon project + R2 bucket, residency selectable per org). No half-measure.",
    },
    {
      title: "HIPAA / BAA",
      status: "not yet",
      body: "We don't sign BAAs today. If you have a healthcare use case, the consent + audit primitives are likely good fits — but please don't put PHI through Aki until we sign a BAA. We'll do this work when there's enough demand to do it right.",
    },
    {
      title: "Penetration test",
      status: "scheduled",
      body: "External pentest scheduled for Q2 2026, scoped to the control plane API, the agent runtime, and the Slack integration. We'll publish a summary with remediation timelines.",
    },
    {
      title: "Bug bounty",
      status: "informal",
      body: "We don't have a public bug bounty yet. We do pay informally for any verified report — rates are negotiated case-by-case until we formalize the program. Disclosure details below.",
    },
  ];

  return (
    <section style={{ padding: "0 56px 60px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: "#ee5959", marginBottom: 16,
      }}>/03 · not yet · honest about it</div>
      <div className="aki-trust-grid" style={{
        display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 18,
      }}>
        {items.map((i) => (
          <div key={i.title} style={{
            padding: "24px 26px", background: "transparent",
            border: `1px dashed ${theme.hair}`,
            display: "flex", flexDirection: "column", gap: 12,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
              <div style={{
                fontFamily: theme.display, fontWeight: 600, fontSize: 22,
                letterSpacing: "-0.015em", lineHeight: 1.2, color: theme.inkLede,
              }}>{i.title}</div>
              <span style={{
                fontFamily: theme.mono, fontSize: 10, color: "#ee5959",
                letterSpacing: "0.18em", textTransform: "uppercase", flexShrink: 0,
              }}>{i.status}</span>
            </div>
            <div style={{
              fontFamily: theme.body, fontSize: 14, color: theme.inkDim,
              lineHeight: 1.6,
            }}>{i.body}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Disclosure() {
  return (
    <section style={{
      margin: "20px 56px 24px", padding: "36px 40px",
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      borderLeft: `2px solid ${theme.accent}`,
    }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, color: theme.accent,
        letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 14,
      }}>responsible disclosure</div>
      <h2 style={{
        margin: 0, fontFamily: theme.display, fontWeight: 600,
        fontSize: 30, lineHeight: 1.15, letterSpacing: "-0.02em",
      }}>
        Found something we should know about?
      </h2>
      <p style={{
        marginTop: 16, fontFamily: theme.body, fontSize: 15,
        color: theme.inkLede, lineHeight: 1.6, maxWidth: 720,
      }}>
        Email{" "}
        <a href="mailto:security@tryclean.ai" style={link}>security@tryclean.ai</a>{" "}
        with reproduction steps. We&apos;ll acknowledge within 24 hours and
        keep you posted with a real fix ETA. We don&apos;t take legal action
        against good-faith research — please don&apos;t exfiltrate customer
        data or impact availability while testing, and we&apos;ll keep
        everything friendly.
      </p>
      <p style={{
        marginTop: 12, fontFamily: theme.mono, fontSize: 12,
        color: theme.inkDim, lineHeight: 1.55,
      }}>
        PGP key fingerprint:{" "}
        <span style={{ color: theme.inkFaint }}>
          available on request · we&apos;ll publish a static key once we&apos;ve had
          enough reports to need one
        </span>
      </p>
    </section>
  );
}

const link: React.CSSProperties = {
  color: theme.accent, textDecoration: "underline",
  textDecorationColor: "rgba(197,236,79,0.4)", textUnderlineOffset: 3,
};

const code: React.CSSProperties = {
  fontFamily: theme.mono, fontSize: 13, background: theme.bg,
  color: theme.inkLede, padding: "1px 6px", borderRadius: 4,
  border: `1px solid ${theme.hair}`,
};
