"use client";

import * as React from "react";
import Link from "next/link";
import { Show, SignUpButton } from "@clerk/nextjs";
import { theme } from "@/lib/theme";
import { MarketingShell } from "@/components/MarketingShell";

/**
 * Aki landing — Glyph II identity, concrete product framing.
 *
 * The brand pieces (Source Serif display, animated grain canvas inside a
 * boxed glyph, lime accent) live here. Sections walk the reader from
 * "what is this" → "how does it work" → "how do you trust it" → CTA.
 * Inline styles are intentional and match the rest of the marketing
 * surfaces.
 */

// ─── shared service glyphs (connectors strip) ────────────────────────────
type SvcKind =
  | "mail" | "chat" | "calendar" | "doc" | "db"
  | "git" | "ticket" | "crm" | "cloud" | "finance";

function SvcGlyph({ kind, size = 20, color = "currentColor" }: { kind: SvcKind; size?: number; color?: string }) {
  const s = size;
  const stroke = { stroke: color, fill: "none", strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (kind) {
    case "mail": return <svg width={s} height={s} viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2" {...stroke}/><path d="M3 8l9 6 9-6" {...stroke}/></svg>;
    case "chat": return <svg width={s} height={s} viewBox="0 0 24 24"><path d="M4 6h16v10H8l-4 3z" {...stroke}/><path d="M8 11h8M8 14h5" {...stroke}/></svg>;
    case "calendar": return <svg width={s} height={s} viewBox="0 0 24 24"><rect x="4" y="6" width="16" height="14" rx="2" {...stroke}/><path d="M4 10h16M9 4v4M15 4v4" {...stroke}/></svg>;
    case "doc": return <svg width={s} height={s} viewBox="0 0 24 24"><path d="M7 3h8l4 4v14H7z" {...stroke}/><path d="M14 3v5h5M10 13h6M10 16h6" {...stroke}/></svg>;
    case "db": return <svg width={s} height={s} viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="7" ry="2.5" {...stroke}/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" {...stroke}/></svg>;
    case "git": return <svg width={s} height={s} viewBox="0 0 24 24"><circle cx="6" cy="6" r="2" {...stroke}/><circle cx="6" cy="18" r="2" {...stroke}/><circle cx="18" cy="12" r="2" {...stroke}/><path d="M6 8v8M8 6h6a4 4 0 0 1 4 4v0" {...stroke}/></svg>;
    case "ticket": return <svg width={s} height={s} viewBox="0 0 24 24"><path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4z" {...stroke}/><path d="M13 6v12" {...stroke} strokeDasharray="2 2"/></svg>;
    case "crm": return <svg width={s} height={s} viewBox="0 0 24 24"><circle cx="9" cy="9" r="3" {...stroke}/><path d="M3 19c1-3.5 3.5-5 6-5s5 1.5 6 5" {...stroke}/><circle cx="17" cy="7" r="2" {...stroke}/><path d="M14 13c1-1 2-1.5 3-1.5s2.5.5 3.5 2.5" {...stroke}/></svg>;
    case "cloud": return <svg width={s} height={s} viewBox="0 0 24 24"><path d="M7 18a4 4 0 1 1 1-7.9A5 5 0 0 1 18 11a3.5 3.5 0 0 1-.5 7z" {...stroke}/></svg>;
    case "finance": return <svg width={s} height={s} viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2" {...stroke}/><path d="M3 10h18M7 15h3" {...stroke}/></svg>;
  }
}

// ─── hero canvas: grain field inside a boxed square ──────────────────────
//
// Earlier this was an SVG <mask> cutting the canvas into the letter 'a'.
// Safari and sometimes Chrome fail to render canvas inside SVG masks —
// leaving just the outline. Plain square grain renders reliably.
function GlyphMarkII({ size = 620 }: { size?: number }) {
  const ref = React.useRef<HTMLCanvasElement | null>(null);

  React.useEffect(() => {
    const cvs = ref.current;
    if (!cvs) return;
    const W = size, H = size;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cvs.width = W * dpr; cvs.height = H * dpr;
    cvs.style.width = W + "px"; cvs.style.height = H + "px";
    const ctx = cvs.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    const NSPARK = 500;
    const NDUST = 2000;
    const sparks = new Array(NSPARK).fill(0).map(() => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.10, vy: (Math.random() - 0.5) * 0.10,
      ph: Math.random() * Math.PI * 2,
      hue: 70 + Math.random() * 20, sat: 70 + Math.random() * 20, lit: 75 + Math.random() * 15,
    }));
    const dust = new Array(NDUST).fill(0).map(() => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.05, vy: (Math.random() - 0.5) * 0.05,
      ph: Math.random() * Math.PI * 2, bri: 0.4 + Math.random() * 0.4,
    }));
    let raf = 0; let alive = true; let paused = false;

    function onVisChange() {
      paused = document.visibilityState === "hidden";
      if (!paused && alive) raf = requestAnimationFrame(frame);
    }
    document.addEventListener("visibilitychange", onVisChange);

    function frame(t: number) {
      if (!alive || !ctx) return;
      if (paused) return;
      ctx.fillStyle = "rgba(21,22,26,0.22)";
      ctx.fillRect(0, 0, W, H);
      for (let i = 0; i < NDUST; i++) {
        const p = dust[i];
        p.x += p.vx + Math.sin(t * 0.0006 + p.ph) * 0.35;
        p.y += p.vy + Math.cos(t * 0.0005 + p.ph * 1.7) * 0.35;
        if (p.x < 0) p.x = W; else if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H; else if (p.y > H) p.y = 0;
        const a = p.bri * (0.4 + 0.3 * Math.sin(t * 0.0015 + p.ph * 3));
        ctx.fillStyle = `rgba(241,237,224,${a})`;
        ctx.fillRect(p.x | 0, p.y | 0, 1, 1);
      }
      for (let i = 0; i < NSPARK; i++) {
        const p = sparks[i];
        p.x += p.vx + Math.sin(t * 0.0009 + p.ph) * 0.55;
        p.y += p.vy + Math.cos(t * 0.0008 + p.ph * 1.7) * 0.55;
        if (p.x < 0) p.x = W; else if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H; else if (p.y > H) p.y = 0;
        const a = 0.45 + 0.45 * Math.sin(t * 0.0022 + p.ph * 3);
        const flare = Math.sin(t * 0.004 + p.ph * 7) > 0.97 ? 2.0 : 1.0;
        ctx.fillStyle = `hsla(${p.hue},${p.sat}%,${p.lit}%,${a * flare * 0.9})`;
        const sz = flare > 1.5 ? 2 : 1;
        ctx.fillRect(p.x | 0, p.y | 0, sz, sz);
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVisChange);
    };
  }, [size]);

  return (
    <div style={{
      position: "relative", width: "100%", maxWidth: size, aspectRatio: "1 / 1",
      border: `1px solid ${theme.hair}`, overflow: "hidden", background: "#0f1014",
    }}>
      <canvas ref={ref} style={{ display: "block", width: "100%", height: "100%" }}/>
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
        letterSpacing: "0.14em",
      }}>
        {[["baseline", "83%"], ["x-height", "46%"], ["cap", "20%"]].map(([label, top]) => (
          <div key={label} style={{
            position: "absolute", left: -8, right: -8, top,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ width: 16, height: 1, background: theme.hair }}/>
            <span style={{ width: 16, height: 1, background: theme.hair }}/>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── page ────────────────────────────────────────────────────────────────
export default function Home() {
  return (
    <MarketingShell>
      <Hero/>
      <Connectors/>
      <HowItWorks/>
      <AgentsMock/>
      <TrustPillars/>
      <SlackDemo/>
      <FinalCTA/>
    </MarketingShell>
  );
}

// ─── hero ────────────────────────────────────────────────────────────────
function Hero() {
  return (
    <section style={{ padding: "40px 56px 60px" }}>
      <div className="aki-hero-grid" style={{
        display: "grid", gridTemplateColumns: "1.05fr 720px 0.95fr",
        gap: 40, alignItems: "center", minHeight: 620,
      }}>
        <div>
          <div style={{
            fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
            textTransform: "uppercase", color: theme.inkFaint, marginBottom: 20,
          }}>
            named agents · v 0.7 · free during beta
          </div>
          <h1 style={{
            margin: 0, fontFamily: theme.display, fontWeight: 600,
            fontSize: 64, lineHeight: 1, letterSpacing: "-0.025em",
          }}>
            Hire your first <span style={{ color: theme.accent, fontWeight: 700 }}>tireless</span>
            <br/>
            <span style={{ fontStyle: "italic", fontWeight: 500 }}>coworker.</span>
          </h1>
          <p style={{
            marginTop: 22, fontFamily: theme.body, fontSize: 17,
            lineHeight: 1.55, color: theme.inkDim, maxWidth: 360,
          }}>
            Aki agents live in your Slack and your stack. Each one runs the work,
            shows the receipts, and asks before anything irreversible.
          </p>
        </div>

        <div className="aki-hero-canvas" style={{ display: "flex", justifyContent: "center" }}>
          <GlyphMarkII size={620}/>
        </div>

        <div className="aki-hero-cta" style={{ textAlign: "right" }}>
          <div style={{
            fontFamily: theme.body, fontSize: 17, fontWeight: 400,
            lineHeight: 1.55, color: theme.inkLede, maxWidth: 320, marginLeft: "auto",
          }}>
            Spin up <em style={{ fontStyle: "italic", color: theme.ink }}>Aki Sales</em>,{" "}
            <em style={{ fontStyle: "italic", color: theme.ink }}>Aki Recruiting</em>, or{" "}
            <em style={{ fontStyle: "italic", color: theme.ink }}>Aki Ops</em> — each one
            its own brief, its own connections, its own audit trail.
          </div>
          <div style={{
            marginTop: 32, display: "flex", flexDirection: "column",
            alignItems: "flex-end", gap: 12,
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
            <span style={{
              fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
              letterSpacing: "0.16em", textTransform: "uppercase",
            }}>free · no waitlist email · 5 min setup</span>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 1080px) {
          .aki-hero-grid {
            grid-template-columns: 1fr !important;
            text-align: center;
          }
          .aki-hero-grid > div { max-width: 620px; margin: 0 auto; }
          .aki-hero-cta { text-align: center !important; }
          .aki-hero-cta > div:last-child { align-items: center !important; }
          .aki-hero-cta > div:first-child { margin: 0 auto !important; }
        }
        @media (max-width: 720px) {
          .aki-hero-grid > div > h1 { font-size: 44px !important; }
          .aki-hero-canvas { max-width: 100%; }
        }
      `}</style>
    </section>
  );
}

const primaryCTA: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 15,
  letterSpacing: "0.01em", padding: "14px 26px", borderRadius: 999,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8,
};

// ─── connectors strip ────────────────────────────────────────────────────
function Connectors() {
  return (
    <section style={{
      padding: "20px 56px",
      borderTop: `1px solid ${theme.hair}`,
      borderBottom: `1px solid ${theme.hair}`,
    }}>
      <div className="aki-conn-row" style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        gap: 24, flexWrap: "wrap",
      }}>
        <span style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>connectors · scoped tokens · audited every call</span>
        <div style={{ display: "flex", gap: 26 }}>
          {(["mail", "chat", "calendar", "doc", "db", "git", "ticket", "crm", "cloud", "finance"] as SvcKind[]).map((k) => (
            <SvcGlyph key={k} kind={k} size={20} color="rgba(241,237,224,0.62)"/>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── /01 · what it does ───────────────────────────────────────────────────
function HowItWorks() {
  const steps: { title: string; body: string; }[] = [
    {
      title: "Write the brief",
      body: "Three questions in plain English. Who is this agent, what tools does it need, what's its first task. The brief becomes its system prompt — you can edit it any time.",
    },
    {
      title: "Connect the tools",
      body: "OAuth into Gmail, Slack, your CRM, your repo, whatever it needs. Scopes are minimal by default. Each connection is shared org-wide or pinned to one agent.",
    },
    {
      title: "Let it run",
      body: "DM it in Slack or chat with it in the app. Long tasks ping you when they finish. Anything that spends money or sends mail outside the team waits for your nod.",
    },
  ];
  return (
    <section style={{ padding: "80px 56px 40px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint,
      }}>/01 · how it works</div>
      <h2 style={{
        margin: "18px 0 0", fontFamily: theme.display, fontWeight: 600,
        fontSize: 52, lineHeight: 1.05, letterSpacing: "-0.025em", maxWidth: 920,
      }}>
        Three minutes to a brief.{" "}
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>The agent does the rest.</span>
      </h2>

      <div className="aki-steps-grid" style={{
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
        gap: 32, marginTop: 56,
      }}>
        {steps.map((s, i) => (
          <div key={s.title} style={{ borderTop: `1px solid ${theme.hair}`, paddingTop: 24 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
              <span style={{
                fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
                letterSpacing: "0.16em",
              }}>0{i + 1}</span>
              <span style={{
                fontFamily: theme.display, fontWeight: 600, fontSize: 32,
                lineHeight: 1.05, letterSpacing: "-0.02em", color: theme.accent,
              }}>{s.title}</span>
            </div>
            <p style={{
              margin: "16px 0 0", fontFamily: theme.body, fontSize: 15,
              lineHeight: 1.55, color: theme.inkLede, maxWidth: 360,
            }}>{s.body}</p>
          </div>
        ))}
      </div>

      <style>{`
        @media (max-width: 900px) {
          .aki-steps-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </section>
  );
}

// ─── /02 · agents page mock (stylised screenshot) ────────────────────────
function AgentsMock() {
  const agents = [
    { name: "Aki Sales", brief: "Inbound demos · qualification · book on AE cal", since: "32 days · 412 actions", color: theme.accent },
    { name: "Aki Recruiting", brief: "Sourcing for senior backend roles · reaches out cold", since: "18 days · 187 actions", color: "#9ec8ff" },
    { name: "Aki Ops", brief: "Linear triage · stale tickets · weekly standup digest", since: "11 days · 96 actions", color: "#e3dcc5" },
  ];

  return (
    <section style={{ padding: "60px 56px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint,
      }}>/02 · the workspace</div>
      <h2 style={{
        margin: "18px 0 32px", fontFamily: theme.display, fontWeight: 600,
        fontSize: 52, lineHeight: 1.05, letterSpacing: "-0.025em", maxWidth: 820,
      }}>
        One workspace.{" "}
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>
          A coworker per job to be done.
        </span>
      </h2>

      <div style={{
        background: theme.bgSoft, border: `1px solid ${theme.hair}`,
        padding: 4, borderRadius: 6, position: "relative",
      }}>
        {/* fake window chrome */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px", borderBottom: `1px solid ${theme.hair}`,
        }}>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: theme.hair }}/>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: theme.hair }}/>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: theme.hair }}/>
          <span style={{
            marginLeft: 18, fontFamily: theme.mono, fontSize: 11,
            color: theme.inkFaint, letterSpacing: "0.12em",
          }}>aki.dev/agents</span>
        </div>

        <div className="aki-mock-shell" style={{
          display: "grid", gridTemplateColumns: "200px 1fr", minHeight: 440,
        }}>
          {/* sidebar */}
          <div style={{
            borderRight: `1px solid ${theme.hair}`,
            padding: "20px 12px", display: "flex", flexDirection: "column", gap: 6,
          }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.22em", textTransform: "uppercase", padding: "0 8px 8px",
            }}>agents</div>
            {agents.map((a, i) => (
              <div key={a.name} style={{
                padding: "8px 10px", borderRadius: 6,
                background: i === 0 ? "rgba(241,237,224,0.06)" : "transparent",
                borderLeft: `2px solid ${i === 0 ? theme.accent : "transparent"}`,
                display: "flex", alignItems: "center", gap: 10,
                fontFamily: theme.body, fontSize: 13,
                color: i === 0 ? theme.ink : theme.inkDim,
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: i === 0 ? theme.accent : theme.inkFaint,
                }}/>
                <span>{a.name}</span>
              </div>
            ))}
            <div style={{
              marginTop: 8, padding: "8px 10px",
              border: `1px dashed ${theme.hair}`, borderRadius: 6,
              fontFamily: theme.body, fontSize: 12, color: theme.inkDim, textAlign: "center",
            }}>+ New agent</div>
          </div>

          {/* main: agent list */}
          <div style={{ padding: "24px 28px" }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 14,
            }}>active · 3</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {agents.map((a) => (
                <div key={a.name} style={{
                  padding: "14px 16px", background: theme.bg,
                  border: `1px solid ${theme.hair}`,
                  display: "grid", gridTemplateColumns: "1fr auto", gap: 14, alignItems: "center",
                }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{
                      fontFamily: theme.display, fontWeight: 600, fontSize: 18,
                      letterSpacing: "-0.015em", color: theme.ink,
                    }}>{a.name}</div>
                    <div style={{
                      marginTop: 4, fontFamily: theme.body, fontSize: 12,
                      color: theme.inkDim, lineHeight: 1.4,
                    }}>{a.brief}</div>
                    <div style={{
                      marginTop: 6, fontFamily: theme.mono, fontSize: 10,
                      color: theme.inkFaint, letterSpacing: "0.14em",
                    }}>{a.since}</div>
                  </div>
                  <span style={{
                    fontFamily: theme.mono, fontSize: 10, color: a.color,
                    letterSpacing: "0.18em", textTransform: "uppercase",
                  }}>● active</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 720px) {
          .aki-mock-shell { grid-template-columns: 1fr !important; }
          .aki-mock-shell > div:first-child { display: none; }
        }
      `}</style>
    </section>
  );
}

// ─── /03 · trust pillars ─────────────────────────────────────────────────
function TrustPillars() {
  const pillars = [
    {
      kicker: "isolation",
      title: "Per-org sandbox. Per-agent process.",
      body: "Each customer gets its own gVisor-sandboxed container. Each agent runs in its own OS process within that container. Postgres row-level security is the second-line defense — a bug can leak nothing across orgs.",
    },
    {
      kicker: "audit",
      title: "Every action is on the record.",
      body: "A hash-chained log captures every tool call, every chat message, every consent decision. You can verify the chain locally with the content_hash + prev_hash fields — no trust required.",
    },
    {
      kicker: "the money rule",
      title: "Spend, send, irrevocable → ask first.",
      body: "Agents have three consent tiers. Anything that costs money, sends mail outside the team, or can't be undone always waits for a human nod. You can tighten the rule — never loosen it past safe defaults.",
    },
  ];

  return (
    <section style={{ padding: "60px 56px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint,
      }}>/03 · trust</div>
      <h2 style={{
        margin: "18px 0 32px", fontFamily: theme.display, fontWeight: 600,
        fontSize: 52, lineHeight: 1.05, letterSpacing: "-0.025em", maxWidth: 820,
      }}>
        Built for the security buyer{" "}
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>before the buyer asked.</span>
      </h2>

      <div className="aki-pillars-grid" style={{
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
        gap: 18, marginTop: 40,
      }}>
        {pillars.map((p) => (
          <div key={p.kicker} style={{
            padding: "26px 26px", background: theme.bgSoft,
            border: `1px solid ${theme.hair}`,
            display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.accent,
              letterSpacing: "0.22em", textTransform: "uppercase",
            }}>{p.kicker}</div>
            <div style={{
              fontFamily: theme.display, fontWeight: 600, fontSize: 22,
              letterSpacing: "-0.015em", lineHeight: 1.2, color: theme.ink,
            }}>{p.title}</div>
            <div style={{
              fontFamily: theme.body, fontSize: 14, color: theme.inkLede,
              lineHeight: 1.55,
            }}>{p.body}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 22, textAlign: "right" }}>
        <Link href="/trust" style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.accent,
          letterSpacing: "0.18em", textTransform: "uppercase", textDecoration: "none",
        }}>read the full trust page →</Link>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .aki-pillars-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </section>
  );
}

// ─── /04 · Slack demo ────────────────────────────────────────────────────
function SlackDemo() {
  const lines: { who: string; whoColor?: string; text: React.ReactNode; tag?: string }[] = [
    {
      who: "Marcus",
      text: <>@<b>aki-sales</b> what came in from the demo form today?</>,
    },
    {
      who: "aki-sales",
      whoColor: theme.accent,
      text: <>3 demo requests since 9am. 2 look qualified — both engineering teams &gt; 50 people. Drafted replies with calendar links and held them for your approval in <a href="/approvals" style={{ color: theme.accent }}>approvals</a>. The third is a personal Gmail address; flagged for manual review.</>,
      tag: "ran 4 tools · cited 3 sources · $0.018",
    },
    {
      who: "Marcus",
      text: <>Approve the two qualified ones. Skip the personal email.</>,
    },
    {
      who: "aki-sales",
      whoColor: theme.accent,
      text: <>Done — both replies sent, both meetings on your AE&apos;s calendar for Thursday. Logged the personal email as &ldquo;manual review · 2026-05-18.&rdquo; Want a daily digest of these?</>,
      tag: "approved · sent · logged",
    },
  ];

  return (
    <section style={{ padding: "60px 56px" }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em",
        textTransform: "uppercase", color: theme.inkFaint,
      }}>/04 · in slack</div>
      <h2 style={{
        margin: "18px 0 32px", fontFamily: theme.display, fontWeight: 600,
        fontSize: 52, lineHeight: 1.05, letterSpacing: "-0.025em", maxWidth: 820,
      }}>
        DM the agent.{" "}
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>Or just @mention it in any channel.</span>
      </h2>

      <div style={{
        background: theme.bgSoft, border: `1px solid ${theme.hair}`,
        padding: "20px 24px", maxWidth: 720,
      }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
          marginBottom: 16, display: "flex", justifyContent: "space-between",
        }}>
          <span># sales-ops</span><span>thursday · 10:14a</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {lines.map((l, i) => (
            <div key={i} style={{
              padding: "10px 14px",
              background: l.whoColor ? "rgba(197,236,79,0.05)" : theme.bg,
              border: `1px solid ${l.whoColor ? "rgba(197,236,79,0.18)" : theme.hair}`,
              borderRadius: 4,
            }}>
              <div style={{
                fontFamily: theme.body, fontSize: 13, fontWeight: 600,
                color: l.whoColor ?? theme.ink, marginBottom: 4,
              }}>{l.who}</div>
              <div style={{
                fontFamily: theme.body, fontSize: 14,
                color: theme.inkLede, lineHeight: 1.5,
              }}>{l.text}</div>
              {l.tag && (
                <div style={{
                  marginTop: 8, fontFamily: theme.mono, fontSize: 10,
                  color: theme.inkFaint, letterSpacing: "0.16em", textTransform: "uppercase",
                }}>{l.tag}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <p style={{
        marginTop: 20, fontFamily: theme.body, fontSize: 14,
        color: theme.inkDim, maxWidth: 720, lineHeight: 1.55,
      }}>
        Install the Aki bot once. After that, every agent you create is mentionable
        from Slack — <code style={{
          fontFamily: theme.mono, fontSize: 13, background: theme.bg,
          color: theme.accent, padding: "1px 6px", borderRadius: 4,
        }}>@aki-sales</code>,{" "}
        <code style={{
          fontFamily: theme.mono, fontSize: 13, background: theme.bg,
          color: theme.accent, padding: "1px 6px", borderRadius: 4,
        }}>@aki-recruiting</code>, and so on.
      </p>
    </section>
  );
}

// ─── final CTA ───────────────────────────────────────────────────────────
function FinalCTA() {
  return (
    <section style={{
      margin: "80px 56px 24px",
      padding: "60px 48px",
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      textAlign: "center",
    }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, color: theme.accent,
        letterSpacing: "0.22em", textTransform: "uppercase", marginBottom: 16,
      }}>free during beta</div>
      <h2 style={{
        margin: 0, fontFamily: theme.display, fontWeight: 600,
        fontSize: 48, lineHeight: 1.05, letterSpacing: "-0.025em",
        maxWidth: 720, marginInline: "auto",
      }}>
        Spin up your first agent today.
        <br/>
        <span style={{ fontStyle: "italic", fontWeight: 500 }}>Three answers and you&rsquo;re working.</span>
      </h2>
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
        <Link href="/docs" style={{
          ...primaryCTA,
          background: "transparent", color: theme.ink,
          border: `1px solid ${theme.hair}`, textDecoration: "none",
        }}>Read the docs</Link>
      </div>
    </section>
  );
}
