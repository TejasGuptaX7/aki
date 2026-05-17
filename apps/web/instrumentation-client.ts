// Client-side instrumentation (Next 16 file convention). Runs before the
// app becomes interactive. We use it to bootstrap Sentry; init is a no-op
// when NEXT_PUBLIC_SENTRY_DSN is unset, so local dev doesn't ship events.
//
// Server-side Sentry would need separate sentry.server.config.ts +
// sentry.edge.config.ts files; the brief only asked for frontend, so we
// haven't wired those.

import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT
      ?? process.env.NODE_ENV
      ?? "development",
    // Trace-sample rate at 10% in prod, full in dev for debuggability.
    tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
    // Send 0 replays today — opt in later via NEXT_PUBLIC_SENTRY_REPLAY_RATE.
    replaysSessionSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_REPLAY_RATE ?? 0),
    replaysOnErrorSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_REPLAY_RATE_ON_ERROR ?? 0),
    // Don't ship breadcrumbs from the noisy fetch wrapper in dev.
    enabled: process.env.NODE_ENV !== "test",
    // Trim PII; Clerk session IDs are still useful and not sensitive.
    sendDefaultPii: false,
  });
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
