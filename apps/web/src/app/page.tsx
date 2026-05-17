"use client";

import * as React from "react";
import Link from "next/link";
import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";

/**
 * Aki landing — direction 03 · II — Glyph (refined).
 *
 * Ported verbatim from /tmp/aki-design/aki/project/directions/glyph2.jsx
 * (Claude Design handoff). Display = Source Serif 4 (variable font wired in
 * layout.tsx), body = Geist, mono = JetBrains Mono. The hero glyph is a giant
 * roman two-story 'a' acting as a mask over a live canvas grain field.
 *
 * Inline styles are intentional — they came from the design prototype and
 * matter for pixel-fidelity. Don't tailwindify without checking against the
 * source.
 */

const theme = {
  bg: "#15161a",
  bgSoft: "#1d1f24",
  ink: "#f1ede0",
  inkLede: "#e3dcc5",
  inkDim: "rgba(241,237,224,0.66)",
  inkFaint: "rgba(241,237,224,0.36)",
  hair: "rgba(241,237,224,0.12)",
  hairSoft: "rgba(241,237,224,0.06)",
  accent: "#c5ec4f",
  accentDim: "rgba(197,236,79,0.18)",
  display: "var(--font-display), 'Times New Roman', serif",
  body: "var(--font-body), system-ui, sans-serif",
  mono: "var(--font-mono), ui-monospace, monospace",
};

// ─── shared: rAF clock hook ───────────────────────────────────────────────
function useTick(): number {
  const [t, setT] = React.useState(0);
  React.useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const loop = (now: number) => {
      setT(now - t0);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  return t;
}

// ─── shared: service icon set ─────────────────────────────────────────────
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

// ─── hero canvas: square of moving grain + sparks ────────────────────────
//
// Earlier this was an SVG <mask> that cut the canvas into the letter 'a'.
// That looks crisp in Stitch's preview but Safari (and sometimes Chrome)
// fail to render canvas content inside SVG foreignObject masks — leaving
// just the letter outline with no grain inside. Plain square grain renders
// reliably and matches what the Stitch design preview actually showed.
function GlyphMarkII({ size = 760 }: { size?: number }) {
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

    const NSPARK = 600;
    const NDUST = 2400;
    const sparks = new Array(NSPARK).fill(0).map(() => ({
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.10,
      vy: (Math.random() - 0.5) * 0.10,
      ph: Math.random() * Math.PI * 2,
      hue: 70 + Math.random() * 20,
      sat: 70 + Math.random() * 20,
      lit: 75 + Math.random() * 15,
    }));
    const dust = new Array(NDUST).fill(0).map(() => ({
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.05,
      vy: (Math.random() - 0.5) * 0.05,
      ph: Math.random() * Math.PI * 2,
      bri: 0.4 + Math.random() * 0.4,
    }));
    let raf = 0;
    let alive = true;
    let paused = false;

    // Pause the rAF loop when the tab is hidden so 3000 particles don't
    // burn frames in the background and grow the JS heap over hours.
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
      position: "relative",
      width: size, height: size,
      border: `1px solid ${theme.hair}`,
      overflow: "hidden",
      background: "#0f1014",
    }}>
      <canvas ref={ref} style={{ display: "block", width: "100%", height: "100%" }}/>

      {/* Type-specimen tick marks on the right edge — kept from glyph2 because
          they made the square feel intentional, like a printer's bracket. */}
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none", fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.14em" }}>
        {[["baseline", "83%"], ["x-height", "46%"], ["cap", "20%"]].map(([label, top]) => (
          <div key={label} style={{ position: "absolute", left: -8, right: -8, top, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ width: 16, height: 1, background: theme.hair }}/>
            <span style={{ width: 16, height: 1, background: theme.hair }}/>
          </div>
        ))}
        <span style={{ position: "absolute", top: "83%", right: -58, transform: "translateY(-50%)" }}>baseline</span>
        <span style={{ position: "absolute", top: "46%", right: -58, transform: "translateY(-50%)" }}>x-height</span>
        <span style={{ position: "absolute", top: "20%", right: -58, transform: "translateY(-50%)" }}>cap</span>
      </div>
    </div>
  );
}

// ─── feature scene: a single decision ─────────────────────────────────────
function GlyphIIDecision() {
  const t = useTick();
  const DUR = 10000;
  const p = (t % DUR) / DUR;

  const A = Math.min(1, Math.max(0, (p - 0.05) / 0.20));
  const B = Math.min(1, Math.max(0, (p - 0.35) / 0.18));
  const C = Math.min(1, Math.max(0, (p - 0.60) / 0.20));
  const fade = p > 0.96 ? 1 - (p - 0.96) / 0.04 : 1;

  const cell = (title: string, kicker: string, body: React.ReactNode, vis: number) => (
    <div style={{ opacity: vis, transform: `translateY(${(1 - vis) * 8}px)` }}>
      <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.accent, letterSpacing: "0.22em", textTransform: "uppercase" }}>{kicker}</div>
      <div style={{ marginTop: 14, fontFamily: theme.display, fontStyle: "italic", fontWeight: 500, fontSize: 34, lineHeight: 1.08, letterSpacing: "-0.015em" }}>{title}</div>
      <div style={{ marginTop: 18 }}>{body}</div>
    </div>
  );

  return (
    <div style={{
      position: "relative",
      background: theme.bgSoft,
      border: `1px solid ${theme.hair}`,
      padding: "36px 40px 40px",
      opacity: fade,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 28 }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.inkFaint }}>
          a single decision · trace #04812
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {["inputs", "policy", "action"].map((label, i) => {
            const v = [A, B, C][i];
            return (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: v > 0.5 ? theme.accent : theme.hair }}/>
                <span style={{ fontFamily: theme.mono, fontSize: 10, color: v > 0.5 ? theme.ink : theme.inkFaint, letterSpacing: "0.16em", textTransform: "uppercase" }}>{label}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr 28px 1fr", alignItems: "stretch", gap: 0 }}>
        {cell(
          "What it read.",
          "inputs · 3",
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              ["thread · 04 may", "Marcus to legal — “30-day exit on renewals, always.”"],
              ["msa · §7.2", "Northwind renewal · auto-renew clause set at 90 days."],
              ["apollon · MSA-2024", "precedent · 30-day exit + EU residency rider."],
            ].map(([k, v], i) => (
              <div key={i} style={{ paddingBottom: 12, borderBottom: `1px dashed ${theme.hair}` }}>
                <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, letterSpacing: "0.04em" }}>{k}</div>
                <div style={{ marginTop: 4, fontFamily: theme.body, fontSize: 14, fontWeight: 400, color: theme.inkLede, lineHeight: 1.5 }}>{v}</div>
              </div>
            ))}
          </div>,
          A,
        )}

        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", opacity: B }}>
          <svg width="24" height="24" viewBox="0 0 24 24"><path d="M3 12h17M14 6l6 6-6 6" fill="none" stroke={theme.accent} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>

        {cell(
          "What you taught it.",
          "policy · 1",
          <div style={{
            padding: "18px 18px",
            background: theme.accentDim,
            border: `1px solid rgba(197,236,79,0.32)`,
          }}>
            <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 10 }}>
              from your brief · vendor contracts
            </div>
            <div style={{ fontFamily: theme.display, fontStyle: "italic", fontWeight: 500, fontSize: 19, lineHeight: 1.45 }}>
              &ldquo;Push back on any renewal clause longer than 30 days. Cite precedent. Loop in finance only if the counter is rejected.&rdquo;
            </div>
            <div style={{ marginTop: 14, fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, letterSpacing: "0.04em" }}>
              match · auto-renew &gt; 30d · confidence 0.96
            </div>
          </div>,
          B,
        )}

        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", opacity: C }}>
          <svg width="24" height="24" viewBox="0 0 24 24"><path d="M3 12h17M14 6l6 6-6 6" fill="none" stroke={theme.accent} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>

        {cell(
          "What it did.",
          "action · 1",
          <div style={{ padding: "16px 18px", background: "rgba(241,237,224,0.04)", border: `1px solid ${theme.hair}` }}>
            <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>draft · reply</div>
            <div style={{ marginTop: 8, fontFamily: theme.body, fontSize: 15, fontWeight: 400, lineHeight: 1.5, color: theme.ink }}>
              Replied to Hana Lin asking for a 30-day exit on the v3 markup. Cited the Apollon precedent and the EU residency rider. Held the draft for your sign-off.
            </div>
            <div style={{ marginTop: 14, display: "flex", gap: 16, fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, letterSpacing: "0.04em" }}>
              <span>reversible · yes</span>
              <span>cost · $0.012</span>
              <span>time · 1.4s</span>
            </div>
          </div>,
          C,
        )}
      </div>
    </div>
  );
}

// ─── page ────────────────────────────────────────────────────────────────
export default function Home() {
  return (
    <div style={{
      width: "100%",
      minHeight: "100vh",
      background: theme.bg,
      color: theme.ink,
      fontFamily: theme.body,
      overflow: "auto",
      position: "relative",
    }}>
      {/* nav */}
      <nav style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "28px 56px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ display: "inline-block", width: 28, height: 28, fontFamily: theme.display, fontWeight: 700, fontSize: 36, lineHeight: 0.78, color: theme.ink, letterSpacing: "-0.04em" }}>a</span>
          <span style={{ fontFamily: theme.body, fontWeight: 600, fontSize: 16, letterSpacing: "0.04em" }}>aki</span>
          <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.12em" }}>v 0.7</span>
        </div>
        <div style={{ display: "flex", gap: 32, alignItems: "center", fontFamily: theme.body, fontSize: 14, fontWeight: 500, color: theme.inkDim }}>
          <span>Product</span><span>Fieldwork</span><span>Pricing</span><span>Company</span>
          <Show when="signed-out">
            <SignInButton mode="modal">
              <span style={{ color: theme.accent, cursor: "pointer" }}>Request access ⟶</span>
            </SignInButton>
          </Show>
          <Show when="signed-in">
            <Link href="/chat" style={{ color: theme.accent, textDecoration: "none" }}>Open app ⟶</Link>
            <UserButton/>
          </Show>
        </div>
      </nav>

      {/* hero */}
      <section style={{ padding: "50px 56px 60px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 780px 1fr", gap: 40, alignItems: "center", minHeight: 760 }}>
          <div>
            <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint, marginBottom: 20 }}>
              an agent · v 0.7 · private beta
            </div>
            <div style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 72, lineHeight: 0.96, letterSpacing: "-0.025em" }}>
              <span style={{ fontStyle: "italic", fontWeight: 500 }}>A small letter</span>
              <span style={{ color: theme.inkDim, fontStyle: "italic", fontWeight: 500 }}>,</span><br/>
              <span style={{ fontWeight: 600 }}>doing</span><br/>
              <span style={{ color: theme.accent, fontWeight: 700 }}>large work.</span>
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "center" }}>
            <GlyphMarkII size={720}/>
          </div>

          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: theme.body, fontSize: 18, fontWeight: 400, lineHeight: 1.55, color: theme.inkLede, maxWidth: 300, marginLeft: "auto" }}>
              Aki connects to your team&rsquo;s systems, takes a brief in your voice, and works the backlog through the night. Every action cites its source. You decide what stands.
            </div>
            <div style={{ marginTop: 32, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 12 }}>
              <Show when="signed-out">
                <SignUpButton mode="modal">
                  <button style={{
                    background: theme.accent, color: theme.bg, border: "none",
                    fontFamily: theme.body, fontWeight: 600, fontSize: 15, letterSpacing: "0.01em",
                    padding: "14px 24px", borderRadius: 999, cursor: "pointer",
                  }}>Request access</button>
                </SignUpButton>
              </Show>
              <Show when="signed-in">
                <Link href="/chat" style={{
                  background: theme.accent, color: theme.bg, border: "none",
                  fontFamily: theme.body, fontWeight: 600, fontSize: 15, letterSpacing: "0.01em",
                  padding: "14px 24px", borderRadius: 999, cursor: "pointer", textDecoration: "none",
                }}>Open app ⟶</Link>
              </Show>
              <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.16em", textTransform: "uppercase" }}>
                142 teams · no waitlist email
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* connectors strip */}
      <section style={{ padding: "20px 56px", borderTop: `1px solid ${theme.hair}`, borderBottom: `1px solid ${theme.hair}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
            14 connectors · scoped SSO
          </span>
          <div style={{ display: "flex", gap: 26 }}>
            {(["mail", "chat", "calendar", "doc", "db", "git", "ticket", "crm", "cloud", "finance"] as SvcKind[]).map((k) => (
              <SvcGlyph key={k} kind={k} size={20} color="rgba(241,237,224,0.62)"/>
            ))}
          </div>
        </div>
      </section>

      {/* what it does */}
      <section style={{ padding: "70px 56px 40px" }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint }}>
          /01 · what it does
        </div>
        <div style={{ marginTop: 18, fontFamily: theme.display, fontWeight: 600, fontSize: 60, lineHeight: 1.05, letterSpacing: "-0.025em", maxWidth: 980 }}>
          Trained on your brief. Connected to your stack. <span style={{ fontStyle: "italic", fontWeight: 500 }}>Honest about every step it took.</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 40, marginTop: 64 }}>
          {[
            ["Brief", "A short letter in plain language. Aki reads it like a contract."],
            ["Connect", "Same access as a senior IC. Scoped tokens, audit per call."],
            ["Cite", "Every action shows its inputs, its policy match, its receipt."],
          ].map(([h, b], i) => (
            <div key={h} style={{ borderTop: `1px solid ${theme.hair}`, paddingTop: 24 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
                <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.16em" }}>0{i + 1}</span>
                <span style={{ fontFamily: theme.display, fontWeight: 600, fontSize: 42, lineHeight: 1, letterSpacing: "-0.02em", color: theme.accent }}>{h}</span>
              </div>
              <div style={{ marginTop: 16, fontFamily: theme.body, fontSize: 16, fontWeight: 400, lineHeight: 1.55, color: theme.inkLede, maxWidth: 320 }}>{b}</div>
            </div>
          ))}
        </div>
      </section>

      {/* feature */}
      <section style={{ padding: "40px 56px 60px" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 22 }}>
          <div>
            <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint }}>
              /02 · trust
            </div>
            <div style={{ marginTop: 12, fontFamily: theme.display, fontWeight: 600, fontSize: 44, letterSpacing: "-0.025em", lineHeight: 1.05 }}>
              Every action is a <span style={{ fontStyle: "italic", fontWeight: 500 }}>small essay.</span>
            </div>
          </div>
          <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.16em" }}>
            remotion · 10s loop · 30fps
          </div>
        </div>
        <GlyphIIDecision/>
      </section>

      {/* type spec */}
      <section style={{ padding: "40px 56px 60px", borderTop: `1px solid ${theme.hair}` }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: theme.inkFaint, marginTop: 30 }}>
          /03 · type
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 56, marginTop: 30, alignItems: "end" }}>
          <div>
            <div style={{ fontFamily: theme.display, fontWeight: 700, fontSize: 220, lineHeight: 0.85, letterSpacing: "-0.04em" }}>
              Aa
            </div>
            <div style={{ fontFamily: theme.mono, fontSize: 11, marginTop: 14, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
              Source Serif 4 · 700 · display 220
            </div>
          </div>
          <div>
            <div style={{ fontFamily: theme.display, fontWeight: 500, fontStyle: "italic", fontSize: 24, lineHeight: 1.45, color: theme.inkLede, letterSpacing: "-0.005em" }}>
              Source Serif gives the wordmark a confident, two-story &lsquo;a&rsquo; that reads at any size. Italic is reserved for cadence — lede, section names, pull quotes — never for the centrepiece.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, auto)", gap: 22, marginTop: 28, fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.14em" }}>
              <span>14 / Geist 400</span>
              <span>18 / Geist 400</span>
              <span>44 / Source 600</span>
              <span>220 / Source 700</span>
            </div>
          </div>
        </div>
      </section>

      {/* rationale */}
      <section style={{
        margin: "0 56px 56px",
        padding: "34px 36px 32px",
        background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.22em", textTransform: "uppercase", color: theme.accent, marginBottom: 16 }}>
          why this design
        </div>
        <div style={{ fontFamily: theme.display, fontWeight: 500, fontSize: 22, fontStyle: "italic", lineHeight: 1.55, maxWidth: 920, letterSpacing: "-0.005em" }}>
          The letter a is the most legible mark in the Latin alphabet — a clear signature for an agent whose job is to make every step legible. Source Serif 4 700 gives it weight; the lime accent gives it life; the grain inside gives it breath.
        </div>
        <div style={{ display: "flex", gap: 28, marginTop: 24, fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
          <span>clearer · heavier · more honest</span>
          <span>typographic · quiet · cited</span>
        </div>
      </section>
    </div>
  );
}
