"use client";

import * as React from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { connectionsApi } from "@/lib/api";
import { useAuthToken } from "@/lib/agents";

/**
 * Native OAuth redirect target.
 *
 * Each provider sends the user back here as
 *   /connect/oauth/callback?code=...&state=...
 * (or `?error=access_denied&error_description=…` if the user bails). We just
 * forward `{code, state}` to `POST /connections/oauth/callback`, which
 * decodes the signed state, exchanges the code for tokens, and upserts the
 * Connection. Then we bounce back to /connect with a status flag.
 *
 * Auth note: the callback endpoint takes NO bearer token — the signed
 * state is the principal. We still send Authorization if Clerk has a
 * session (helps for CORS preflight uniformity), but the backend ignores it.
 */
export default function OAuthCallbackPage() {
  return (
    <React.Suspense fallback={<CallbackChrome>Verifying…</CallbackChrome>}>
      <CallbackInner />
    </React.Suspense>
  );
}

function CallbackInner() {
  const search = useSearchParams();
  const router = useRouter();
  const tok = useAuthToken();
  const [status, setStatus] = React.useState<string>("Exchanging authorization code…");

  // Run-once: we never want to re-POST the code if React strict-mode or a
  // hot-reload triggers the effect a second time. Codes are single-use.
  const fired = React.useRef(false);

  React.useEffect(() => {
    if (fired.current) return;
    fired.current = true;

    const code = search?.get("code");
    const state = search?.get("state");
    const oauthErr = search?.get("error");
    const oauthErrDesc = search?.get("error_description");

    if (oauthErr) {
      const msg = oauthErrDesc ? `${oauthErr}: ${oauthErrDesc}` : oauthErr;
      bounceToConnect(router, { err: msg });
      return;
    }
    if (!code || !state) {
      bounceToConnect(router, { err: "missing code or state in callback" });
      return;
    }

    (async () => {
      try {
        const conn = await connectionsApi.oauthCallback(tok, { code, state });
        setStatus(`Connected ${conn.provider}. Redirecting…`);
        bounceToConnect(router, {
          ok: true,
          agentId: conn.agent_id ?? undefined,
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        bounceToConnect(router, { err: msg });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <CallbackChrome>{status}</CallbackChrome>;
}

function bounceToConnect(
  router: ReturnType<typeof useRouter>,
  opts: { ok?: boolean; err?: string; agentId?: string },
) {
  const params = new URLSearchParams();
  if (opts.ok) params.set("ok", "1");
  if (opts.err) params.set("err", opts.err);
  if (opts.agentId) params.set("agent_id", opts.agentId);
  const qs = params.toString();
  router.replace(`/connect${qs ? `?${qs}` : ""}`);
}

function CallbackChrome({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: theme.bg,
        color: theme.ink,
        fontFamily: theme.body,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
      }}
    >
      <div
        style={{
          maxWidth: 480,
          padding: "32px 36px",
          background: theme.bgSoft,
          border: `1px solid ${theme.hair}`,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: theme.mono,
            fontSize: 11,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: theme.inkFaint,
            marginBottom: 18,
          }}
        >
          connecting
        </div>
        <div
          style={{
            fontFamily: theme.display,
            fontWeight: 600,
            fontSize: 22,
            letterSpacing: "-0.015em",
            color: theme.ink,
          }}
        >
          {children}
        </div>
      </div>
    </main>
  );
}
