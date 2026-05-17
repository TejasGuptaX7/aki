"use client";

import * as React from "react";
import Link from "next/link";
import { theme } from "@/lib/theme";

/**
 * Global error boundary. The ErrorBoundary inside AppShell catches render
 * errors in the app surfaces; this catches everything else (root layout,
 * marketing pages, route handlers). Must be a client component per Next 16
 * convention.
 */
export default function GlobalError({ error, reset }: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Real error reporting (Sentry, etc.) would go here when we wire it.
    // For now, keep the digest visible so support can correlate with logs.
  }, [error]);

  return (
    <div style={{
      minHeight: "100vh", background: theme.bg, color: theme.ink,
      fontFamily: theme.body, display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", padding: "48px 24px",
      textAlign: "center",
    }}>
      <div style={{
        fontFamily: theme.mono, fontSize: 11, color: "#ee5959",
        letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 24,
      }}>error · 500</div>

      <div style={{
        fontFamily: theme.display, fontWeight: 700, fontSize: 140,
        lineHeight: 0.85, letterSpacing: "-0.04em", color: theme.ink,
        marginBottom: 24, fontStyle: "italic",
      }}>!</div>

      <h1 style={{
        margin: 0, fontFamily: theme.display, fontWeight: 600,
        fontSize: 44, letterSpacing: "-0.025em", lineHeight: 1.05,
      }}>
        Something cracked.
      </h1>
      <p style={{
        margin: "16px auto 0", fontFamily: theme.body, fontSize: 17,
        color: theme.inkLede, lineHeight: 1.55, maxWidth: 480,
      }}>
        A page threw while rendering. Try again — if it keeps happening,
        the error ID below is what our support team needs to find it in
        the logs.
      </p>

      {error.digest && (
        <code style={{
          marginTop: 18, padding: "6px 12px",
          background: theme.bgSoft, border: `1px solid ${theme.hair}`,
          fontFamily: theme.mono, fontSize: 12, color: theme.inkLede,
          borderRadius: 4,
        }}>{error.digest}</code>
      )}

      <div style={{
        marginTop: 28, display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center",
      }}>
        <button onClick={reset} style={pillPrimary}>Try again</button>
        <Link href="/" style={pillSecondary}>Go home</Link>
        <a href="mailto:hello@tryclean.ai" style={pillSecondary}>Email support</a>
      </div>
    </div>
  );
}

const pillPrimary: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 14,
  padding: "12px 22px", borderRadius: 999, cursor: "pointer",
};

const pillSecondary: React.CSSProperties = {
  background: "transparent", color: theme.ink,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 14,
  padding: "11px 22px", borderRadius: 999, textDecoration: "none",
};
