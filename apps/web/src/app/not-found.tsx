import type { Metadata } from "next";
import Link from "next/link";
import { theme } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Not found — Aki",
};

export default function NotFound() {
  return (
    <div style={{
      minHeight: "100vh", background: theme.bg, color: theme.ink,
      fontFamily: theme.body, display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", padding: "48px 24px",
      textAlign: "center",
    }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
        letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 24,
      }}>error · 404</div>

      <div style={{
        fontFamily: theme.display, fontWeight: 700, fontSize: 180,
        lineHeight: 0.85, letterSpacing: "-0.04em", color: theme.accent,
        marginBottom: 24,
      }}>a</div>

      <h1 style={{
        margin: 0, fontFamily: theme.display, fontWeight: 600,
        fontSize: 48, letterSpacing: "-0.025em", lineHeight: 1.05,
      }}>
        That page doesn&rsquo;t exist.
      </h1>
      <p style={{
        margin: "16px auto 0", fontFamily: theme.body, fontSize: 17,
        color: theme.inkLede, lineHeight: 1.55, maxWidth: 460,
      }}>
        Either a typo, a stale link, or a page we moved. Try one of these
        instead — or head back to the start.
      </p>

      <div style={{
        marginTop: 32, display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center",
      }}>
        <Link href="/" style={pillPrimary}>Go home</Link>
        <Link href="/docs" style={pillSecondary}>Read the docs</Link>
        <Link href="/chat" style={pillSecondary}>Open the app</Link>
      </div>
    </div>
  );
}

const pillPrimary: React.CSSProperties = {
  background: theme.accent, color: theme.bg,
  fontFamily: theme.body, fontWeight: 600, fontSize: 14,
  padding: "12px 22px", borderRadius: 999, textDecoration: "none",
};

const pillSecondary: React.CSSProperties = {
  background: "transparent", color: theme.ink,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 14,
  padding: "11px 22px", borderRadius: 999, textDecoration: "none",
};
