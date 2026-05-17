"""Minimal direct Slack Web API client used by the webhook reply path.

The agent has its own `slack_post_message` MCP tool (see app/oauth/slack.py)
that talks to Slack with the per-org token from Connection.config; THIS
module is the simpler fallback path used by routes/slack.py when we want
to post a reply on behalf of the agent without going through MCP — e.g.
the rate-limit-exceeded notice.

Token source: SLACK_BOT_TOKEN env var. In multi-tenant deployments this
is empty and the webhook resolver loads the per-org token directly from
`Connection.config.access_token` before calling post_message. Single-
tenant dev / staging keeps the env var as a convenience.

Scope is intentionally tiny — chat.postMessage is the only call the
agent reply path needs. Add more methods as the product needs them.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings


log = logging.getLogger(__name__)
_SLACK_API_BASE = "https://slack.com/api"


class SlackError(RuntimeError):
    def __init__(self, msg: str, *, response: dict | None = None):
        super().__init__(msg)
        self.response = response or {}


def _token() -> str:
    s = get_settings()
    if not s.slack_bot_token:
        raise SlackError("SLACK_BOT_TOKEN not configured")
    return s.slack_bot_token


async def post_message(
    channel: str,
    text: str,
    *,
    thread_ts: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> dict:
    """Post a plain-text message to a Slack channel or DM. Channel can be a
    channel id (C…), DM id (D…), or user id (U… — Slack accepts that as
    a DM target).

    Returns Slack's response dict. On `ok: false`, raises SlackError with
    the response body attached. Common failures:
      - `not_in_channel` — bot must be invited via /invite @aki first
      - `channel_not_found` — wrong id, or bot not in workspace
      - `invalid_auth` — token wrong / revoked
    """
    body: dict[str, Any] = {"channel": channel, "text": text}
    if thread_ts:
        body["thread_ts"] = thread_ts
    if blocks:
        body["blocks"] = blocks

    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(
            f"{_SLACK_API_BASE}/chat.postMessage",
            headers={
                "Authorization": f"Bearer {_token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=body,
        )
    data = r.json() if r.content else {}
    if not data.get("ok"):
        log.warning(
            "slack chat.postMessage failed channel=%s error=%s",
            channel, data.get("error"),
        )
        raise SlackError(
            f"chat.postMessage failed: {data.get('error', 'unknown')}",
            response=data,
        )
    return data
