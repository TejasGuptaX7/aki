"use client";

import * as React from "react";
import * as Sentry from "@sentry/nextjs";
import { theme } from "@/lib/theme";

type State = { error: Error | null };

/**
 * Catch render errors in pages so one component crash doesn't blank the
 * whole shell. React's docs say this still needs to be a class component
 * — no hook equivalent for componentDidCatch yet.
 *
 * Render crashes are also forwarded to Sentry via captureException so the
 * "Something cracked." card shown to the user has a real backing trace.
 * Sentry no-ops when NEXT_PUBLIC_SENTRY_DSN is unset.
 */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    Sentry.captureException(error, {
      tags: { source: "react-error-boundary" },
      extra: { componentStack: info.componentStack ?? null },
    });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{
        padding: "48px 56px", color: theme.ink,
        fontFamily: theme.body, background: theme.bg, minHeight: "100vh",
      }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, letterSpacing: "0.24em", textTransform: "uppercase", color: "#ee5959", marginBottom: 14 }}>
          render error
        </div>
        <h1 style={{ margin: 0, fontFamily: theme.display, fontWeight: 600, fontSize: 36, letterSpacing: "-0.02em", marginBottom: 14 }}>
          Something cracked.
        </h1>
        <p style={{ fontFamily: theme.body, color: theme.inkLede, fontSize: 16, lineHeight: 1.55, maxWidth: 620 }}>
          A page component threw while rendering. Refresh to retry. If it keeps happening, the details below are the smoking gun.
        </p>
        <pre style={{
          marginTop: 28, padding: "16px 18px",
          background: theme.bgSoft, border: `1px solid ${theme.hair}`,
          fontFamily: theme.mono, fontSize: 12, color: theme.inkLede,
          overflowX: "auto", whiteSpace: "pre-wrap",
        }}>
          {this.state.error.message}{"\n\n"}
          {this.state.error.stack?.split("\n").slice(0, 8).join("\n")}
        </pre>
        <button
          onClick={() => this.setState({ error: null })}
          style={{
            marginTop: 20,
            background: theme.accent, color: theme.bg, border: "none",
            fontFamily: theme.body, fontWeight: 600, fontSize: 14,
            padding: "10px 22px", borderRadius: 999, cursor: "pointer",
          }}
        >
          Try again
        </button>
      </div>
    );
  }
}
