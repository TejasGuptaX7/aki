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

Reply path: the agent's chat is invoked with a synthetic system context
describing the Slack message; the agent's response text is captured from
the stream and posted back via slack_client.post_message. The agent has
access to `slack_post_message` via the native MCP server (app/oauth/slack.py)
for cases where it wants to post elsewhere mid-task.

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
    """Find which org owns this Slack workspace.

    Native Slack OAuth (app/oauth/slack.py) stores team_id directly in
    config; the legacy slack_bot / Arcade-mediated paths nest it under
    `metadata.team_id` or `slack_team_id` — check all three."""
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
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
            if (
                cfg.get("team_id") == team_id
                or cfg.get("slack_team_id") == team_id
                or (cfg.get("metadata") or {}).get("team_id") == team_id
                or (cfg.get("team") or {}).get("id") == team_id
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

    Reply model: the agent generates a text response; we capture it from
    the stream and POST directly to Slack via slack_client. The agent's
    native `slack_post_message` tool exists (see app/oauth/slack.py) but
    isn't on the reply path for this flow — keeps the agent from
    accidentally posting twice."""
    from app.agent_runtime import ensure_agent_loaded
    from app.rate_limits import Kind as RLKind, enforce_daily_cap, record_usage
    from app.slack_client import SlackError, post_message
    import httpx
    import json as _json

    # Strip the leading slug mention from the text so the agent sees the
    # actual question, not "@aki-sales tell me ...".
    cleaned = _MENTION_PATTERN.sub("", text_in.strip(), count=1).strip() or text_in

    composed_user = (
        f"You received a Slack DM from user <@{slack_user}> in channel "
        f"`{channel}`:\n\n{cleaned}\n\n"
        f"Reply with a brief, conversational message — this is Slack, not "
        f"email. Don't try to call slack_bot tools yourself; the platform "
        f"will post your reply for you. If this asks for a tier-2 action "
        f"(external email, public post, account signup), gate it via "
        f"request_approval first and tell the user it's pending."
    )

    async with session_for_org(org_id) as db:
        try:
            await enforce_daily_cap(db, org_id, RLKind.ACTIONS)
            await enforce_daily_cap(db, org_id, RLKind.LLM_CENTS)
        except HTTPException:
            log.warning("slack: rate-limit hit for org=%s, skipping reply", org_id)
            try:
                await post_message(
                    channel,
                    ":hourglass_flowing_sand: Aki is over today's usage cap. "
                    "Resets at midnight UTC.",
                )
            except SlackError:
                log.exception("slack: failed to post rate-limit notice")
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

        # Accumulate the assistant's visible content from the SSE stream
        # so we can post it back to Slack. tool-call chunks are skipped.
        assistant_parts: list[str] = []
        tail = ""
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
                    async for raw in upstream.aiter_bytes():
                        try:
                            tail += raw.decode("utf-8", errors="replace")
                        except Exception:
                            continue
                        # Parse SSE blocks separated by "\n\n".
                        while True:
                            sep = tail.find("\n\n")
                            if sep == -1:
                                break
                            block = tail[:sep]
                            tail = tail[sep + 2:]
                            for line in block.split("\n"):
                                if not line.startswith("data:"):
                                    continue
                                data_str = line[5:].lstrip()
                                if data_str == "[DONE]":
                                    continue
                                try:
                                    obj = _json.loads(data_str)
                                except Exception:
                                    continue
                                choices = (obj or {}).get("choices") or []
                                if choices:
                                    piece = (
                                        (choices[0] or {}).get("delta") or {}
                                    ).get("content")
                                    if isinstance(piece, str) and piece:
                                        assistant_parts.append(piece)
            await record_usage(db, org_id, RLKind.ACTIONS, 1)
            await db.commit()
        except Exception:
            log.exception(
                "slack: chat invocation failed org=%s agent=%s",
                org_id, agent.id,
            )
            try:
                await post_message(
                    channel,
                    ":warning: Aki hit an error processing that. The trail "
                    "is in your audit log.",
                )
            except SlackError:
                log.exception("slack: failed to post error notice")
            return

        reply_text = "".join(assistant_parts).strip()
        if not reply_text:
            # Agent ran tools or returned no visible text; tell the user
            # something happened so they're not staring at an empty thread.
            reply_text = (
                ":thinking_face: Aki processed that but didn't have a "
                "text reply. Check the audit log if you wanted to see tool "
                "activity."
            )
        try:
            await post_message(channel, reply_text)
        except SlackError as e:
            log.exception(
                "slack: chat.postMessage failed channel=%s detail=%s",
                channel, e.response,
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
            "slack event from unknown team_id=%s (no active slack "
            "connection). Did the workspace install Aki via /connect?",
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
