"""Slack native OAuth handler.

Replaces the single-tenant SLACK_BOT_TOKEN env var with per-workspace
installations. Each org install creates a Connection row whose config
holds `access_token` (bot token, `xoxb-…`), `team_id`, and `bot_user_id`.

Slack's OAuth v2 token endpoint returns a custom shape (no `expires_in`,
no `refresh_token` by default — bot tokens don't expire unless the
workspace enables token rotation). We don't refresh by default; if a
workspace flips on rotation, the refresh_token field becomes present and
the base handler's refresh path kicks in.

Setup (founder):
  1. api.slack.com → Create New App → From scratch → name "Aki".
  2. OAuth & Permissions → Redirect URLs:
       ${WEB_BASE_URL}/connect/oauth/callback
  3. Bot Token Scopes: `chat:write`, `channels:read`, `groups:read`,
     `users:read`, `app_mentions:read`. (Add `chat:write.public` for
     posting to channels Aki isn't a member of.)
  4. Basic Information → copy Client ID + Client Secret + Signing Secret
     into SLACK_CLIENT_ID / SLACK_CLIENT_SECRET / SLACK_SIGNING_SECRET.
  5. Install to your home workspace once — the install URL Aki generates
     is what we hand to other workspaces.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Connection
from app.oauth.base import (
    NativeOAuthError,
    NativeToolSpec,
    OAuthHandler,
    _register,
)


log = logging.getLogger(__name__)


# Bot scopes; user scopes are NOT requested in v1 (we don't act-as-user).
SLACK_BOT_SCOPES = [
    "chat:write",
    "chat:write.public",
    "channels:read",
    "channels:history",
    "groups:read",
    "users:read",
    "users:read.email",
    "app_mentions:read",
]


async def _slack_post(method: str, token: str, json: dict) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.post(
            f"https://slack.com/api/{method}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=json,
        )
    body = r.json() if r.content else {}
    if r.status_code >= 400 or not body.get("ok", False):
        raise NativeOAuthError(
            f"slack {method} failed",
            status=r.status_code,
            body=str(body)[:500],
        )
    return body


async def _slack_get(method: str, token: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.get(
            f"https://slack.com/api/{method}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
    body = r.json() if r.content else {}
    if r.status_code >= 400 or not body.get("ok", False):
        raise NativeOAuthError(
            f"slack {method} failed",
            status=r.status_code,
            body=str(body)[:500],
        )
    return body


# ── Tool callables ──────────────────────────────────────────────────────────


async def _post_message(args: dict, conn: Connection, db: AsyncSession) -> Any:
    """Post to a Slack channel. TIER-2."""
    token = (conn.config or {}).get("access_token")
    channel = (args.get("channel") or "").strip()
    text = args.get("text") or ""
    if not channel or not text:
        raise NativeOAuthError("channel and text required")
    body: dict[str, Any] = {"channel": channel, "text": text}
    if args.get("thread_ts"):
        body["thread_ts"] = args["thread_ts"]
    if args.get("blocks"):
        body["blocks"] = args["blocks"]
    return await _slack_post("chat.postMessage", token, body)


async def _list_channels(args: dict, conn: Connection, db: AsyncSession) -> Any:
    token = (conn.config or {}).get("access_token")
    return await _slack_get(
        "conversations.list",
        token,
        {
            "limit": min(int(args.get("limit") or 100), 1000),
            "exclude_archived": "true",
            "types": args.get("types") or "public_channel,private_channel",
        },
    )


# ── Handler ─────────────────────────────────────────────────────────────────


class SlackHandler(OAuthHandler):
    provider_slug = "slack"
    display_provider = "slack"
    authorize_url = "https://slack.com/oauth/v2/authorize"
    token_url = "https://slack.com/api/oauth.v2.access"
    default_scopes = SLACK_BOT_SCOPES
    scope_delimiter = ","

    def client_id(self) -> str | None:
        return get_settings().slack_client_id

    def client_secret(self) -> str | None:
        return get_settings().slack_client_secret

    def post_token_exchange(self, token_response: dict) -> dict:
        """Slack's response shape: bot token lives at top-level
        `access_token`, but `authed_user.access_token` is the user-scope
        token if user scopes were requested. We only request bot scopes,
        so the top-level is what we want — already aligned with
        access_token_field's default. Pull the team_id out so the upstream
        Slack webhook router can find the right Connection on incoming
        events."""
        out = dict(token_response)
        team = token_response.get("team") or {}
        if "id" in team and "team_id" not in out:
            out["team_id"] = team["id"]
        return out

    def tools(self) -> list[NativeToolSpec]:
        return [
            NativeToolSpec(
                name="slack_post_message",
                description=(
                    "Post a message to a Slack channel. `channel` may be the "
                    "channel id (C…), name (#general), or DM target (@user). "
                    "TIER-2: request_approval before sending."
                ),
                input_schema={
                    "type": "object",
                    "required": ["channel", "text"],
                    "properties": {
                        "channel": {"type": "string"},
                        "text": {"type": "string"},
                        "thread_ts": {"type": "string"},
                        "blocks": {"type": "array"},
                    },
                },
                caller=_post_message,
            ),
            NativeToolSpec(
                name="slack_list_channels",
                description="List channels Aki has been invited to in the workspace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 100},
                        "types": {
                            "type": "string",
                            "default": "public_channel,private_channel",
                        },
                    },
                },
                caller=_list_channels,
            ),
        ]


_register(SlackHandler())
