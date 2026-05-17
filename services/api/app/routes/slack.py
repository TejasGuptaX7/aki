"""POST /webhooks/slack — Slack Events API listener.

Two-phase request lifecycle (Slack contract):

  1. Slack POSTs the event.
  2. We MUST return 200 within 3 seconds or Slack retries (and eventually
     disables the subscription). So this handler:
       a. verifies the signing secret (HMAC-SHA256 over a canonical body)
       b. handles `url_verification` synchronously (echo the challenge)
       c. for `event_callback`: schedules a background task and returns
          200 immediately. The background task does the real work
          (parse mention → resolve agent → run chat → agent replies via
          its own slack_bot MCP tool).

Reply path is elegant: we don't post to Slack from this handler. Instead,
the agent's chat is invoked with a synthetic system context describing
the Slack message, and the agent uses its OWN `slack_bot` MCP tool
(from Pipedream Connect) to post the response. That way the agent's
audit trail and rate limits cover Slack the same way they cover web chat.

Org resolution: the Slack `team_id` in the event payload maps to one of
our Connection rows (provider='slack_bot', config has the team_id
stored at OAuth-complete time). One Slack workspace → one org.

Mention parsing:
  "@aki-sales find me 5 leads"          → agent slug "aki-sales"
  "<@U12345> find me 5 leads"           → bare bot mention, default agent
  DM (channel type 'im'): no mention required, default agent
  Specific agent in DM: still parseable by prefix "@<slug> ..."
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select, text

from app.audit import append_audit
from app.config import get_settings
from app.db import SessionLocal, session_for_org
from app.models import Agent, Connection


log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Signing-secret verification ────────────────────────────────────────────


# Reject events with timestamps more than 5 minutes off — protects against
# replay attacks per Slack's docs.
MAX_TIMESTAMP_SKEW_S = 60 * 5


def _verify_slack_signature(
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    signing_secret: str,
) -> bool:
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > MAX_TIMESTAMP_SKEW_S:
        return False

    base = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(
        signing_secret.encode(), base, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Org + agent resolution ─────────────────────────────────────────────────


_MENTION_PATTERN = re.compile(
    r"""
    ^                       # start of cleaned text
    (?:<@[^>]+>\s*)?        # optional bare bot mention <@U12345>
    @?                      # optional literal @
    (?P<slug>[a-z0-9][a-z0-9-]*) # the slug we care about
    \s+                     # mandatory whitespace separating slug from message
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _parse_agent_slug(text_in: str) -> str | None:
    """Pull an agent slug from a Slack message's text, if present.

    Returns the slug (e.g. 'aki-sales') or None if no recognizable mention.
    Slug matches our /agents.slug regex shape (lowercase + hyphens).
    """
    if not text_in:
        return None
    m = _MENTION_PATTERN.match(text_in.strip())
    return m.group("slug").lower() if m else None


async def _resolve_org_by_slack_team(team_id: str) -> UUID | None:
    """Find which org owns this Slack workspace. The Pipedream Slack-bot
    connection records the team_id in config when OAuth completes."""
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        # Match either provider='slack_bot' OR provider='slack' (legacy),
        # with team_id in the config jsonb.
        rows = (
            await db.execute(
                select(Connection).where(
                    Connection.provider.in_(("slack_bot", "slack")),
                    Connection.status == "active",
                )
            )
        ).scalars().all()
        for r in rows:
            cfg = r.config or {}
            # Pipedream's account responses include team_id at various
            # key paths depending on the toolkit version — check the
            # likely names.
            if (
                cfg.get("team_id") == team_id
                or cfg.get("slack_team_id") == team_id
                or (cfg.get("metadata") or {}).get("team_id") == team_id
            ):
                return r.organization_id
    return None


async def _resolve_agent(
    org_id: UUID, slug_hint: str | None
) -> Agent | None:
    """Get the agent matching slug_hint, or fall back to the default
    'aki' agent, or first-active if neither exists."""
    async with session_for_org(org_id) as db:
        if slug_hint:
            a = await db.scalar(
                select(Agent).where(
                    Agent.organization_id == org_id,
                    Agent.slug == slug_hint,
                    Agent.status == "active",
                )
            )
            if a is not None:
                return a
        # Fall back to default
        a = await db.scalar(
            select(Agent).where(
                Agent.organization_id == org_id,
                Agent.slug == "aki",
                Agent.status == "active",
            )
        )
        if a is not None:
            return a
        # Last resort: any active agent
        return await db.scalar(
            select(Agent).where(
                Agent.organization_id == org_id,
                Agent.status == "active",
            ).order_by(Agent.created_at.asc()).limit(1)
        )


# ── Background processor ───────────────────────────────────────────────────


async def _process_slack_message(
    org_id: UUID,
    agent: Agent,
    channel: str,
    slack_user: str,
    text_in: str,
    event_ts: str,
) -> None:
    """The real work — runs after the webhook returns 200.

    Builds a synthetic user message that gives the agent enough context
    to reply via its slack_bot tool. The agent's normal chat path handles
    everything: audit, rate limits, tool calls (including the Slack post),
    consent if applicable. No direct Slack API call from this code —
    the agent owns the reply.
    """
    from app.agent_runtime import ensure_agent_loaded
    from app.audit import append_audit
    from app.rate_limits import Kind as RLKind, enforce_daily_cap, record_usage
    from app.pricing import estimate_cost_usd
    import httpx

    settings = get_settings()

    # Strip the leading slug mention from the text (the agent doesn't
    # need to re-parse it) so the user_text is the actual question.
    cleaned = _MENTION_PATTERN.sub("", text_in.strip(), count=1).strip() or text_in

    composed_user = (
        f"You received a Slack message in channel `{channel}` from user "
        f"<@{slack_user}>:\n\n{cleaned}\n\n"
        f"Reply by posting to that same channel using your slack_bot "
        f"chat.postMessage tool (channel={channel}). Be brief — Slack "
        f"is conversational. If the request is tier-2 (sending external "
        f"messages, signing up for things), gate it via request_approval "
        f"first."
    )

    async with session_for_org(org_id) as db:
        try:
            await enforce_daily_cap(db, org_id, RLKind.ACTIONS)
            await enforce_daily_cap(db, org_id, RLKind.LLM_CENTS)
        except HTTPException:
            log.warning("slack: rate-limit hit for org=%s, skipping reply", org_id)
            # TODO: post a "you've hit your daily cap" message via Slack
            # API directly so the user knows we got their message.
            return

        container = await ensure_agent_loaded(db, org_id, agent.id)
        await append_audit(
            db, org_id,
            actor=f"slack:{slack_user}",
            action="slack.event",
            target=channel,
            payload={"event_ts": event_ts, "channel": channel,
                     "slack_user": slack_user, "len": len(text_in)},
            agent_id=agent.id,
        )
        await db.commit()

        # System prompt comes from the agent's record; we prepend like the
        # web chat path does.
        body = {
            "model": "hermes-agent",
            "stream": True,
            "messages": [
                {"role": "system", "content": agent.system_prompt},
                {"role": "user", "content": composed_user},
            ],
        }

        headers = {
            "Authorization": f"Bearer {container.supervisor_api_key}",
            "Content-Type": "application/json",
            "X-Aki-Agent-Id": str(agent.id),
        }

        # Drain the SSE response — don't bother accumulating content,
        # the agent posts to Slack via its own MCP tool. We just need
        # the chat loop to RUN.
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(600.0, connect=10.0)
            ) as c:
                async with c.stream(
                    "POST",
                    f"{container.base_url}/v1/chat/completions",
                    json=body,
                    headers=headers,
                ) as upstream:
                    async for _ in upstream.aiter_bytes():
                        pass
            await record_usage(db, org_id, RLKind.ACTIONS, 1)
            await db.commit()
        except Exception:
            log.exception(
                "slack: chat invocation failed org=%s agent=%s",
                org_id, agent.id,
            )


# ── HTTP handler ───────────────────────────────────────────────────────────


@router.post("/slack")
async def slack_webhook(request: Request) -> Response:
    settings = get_settings()
    if not settings.slack_signing_secret:
        raise HTTPException(503, "SLACK_SIGNING_SECRET not configured")

    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(413, "webhook body too large")

    if not _verify_slack_signature(
        body,
        request.headers.get("X-Slack-Request-Timestamp"),
        request.headers.get("X-Slack-Signature"),
        settings.slack_signing_secret,
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad slack signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")

    # Slack uses this once at subscription-time to confirm our endpoint.
    if payload.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": payload.get("challenge", "")}),
            media_type="application/json",
        )

    if payload.get("type") != "event_callback":
        # Other top-level types (e.g. "app_uninstalled") — ack and ignore.
        return Response(status_code=200)

    event = payload.get("event") or {}
    event_type = event.get("type")
    team_id = payload.get("team_id")

    # Subtypes to handle: 'message' in DMs (channel type 'im') + 'app_mention'.
    # Skip bot's own messages (would loop infinitely otherwise).
    if event_type not in ("message", "app_mention"):
        return Response(status_code=200)
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return Response(status_code=200)
    if event_type == "message" and event.get("channel_type") != "im":
        # Plain channel message that isn't an app_mention — not for us.
        return Response(status_code=200)

    channel = event.get("channel")
    slack_user = event.get("user")
    text_in = event.get("text") or ""
    event_ts = event.get("ts") or ""

    if not (team_id and channel and slack_user):
        log.warning("slack event missing required fields: %s", event)
        return Response(status_code=200)

    org_id = await _resolve_org_by_slack_team(team_id)
    if org_id is None:
        log.warning(
            "slack event from unknown team_id=%s (no active slack_bot "
            "connection). Did the workspace install Aki via Pipedream?",
            team_id,
        )
        return Response(status_code=200)

    agent = await _resolve_agent(org_id, _parse_agent_slug(text_in))
    if agent is None:
        log.warning("slack event for org=%s but no active agent", org_id)
        return Response(status_code=200)

    # Fire-and-forget so we return 200 within Slack's 3s window.
    # The exception handler logs but doesn't surface — the user sees
    # "Aki didn't respond" instead of a Slack-side error, which is fine
    # for an MVP.
    asyncio.create_task(
        _process_slack_message(
            org_id, agent, channel, slack_user, text_in, event_ts
        )
    )

    return Response(status_code=200)
