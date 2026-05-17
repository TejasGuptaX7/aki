"""Gmail native OAuth handler.

Uses the Google Identity OAuth 2.0 server flow with the Gmail API scopes.
Same OAuth client works for Calendar and Drive — we register one Google
Cloud project, request the union of needed scopes, and split tool surfaces
by provider_slug.

Setup (founder):
  1. Google Cloud Console → Create a project (or use existing).
  2. APIs & Services → OAuth consent screen → External; add Aki branding.
  3. Credentials → Create OAuth client ID → Web application.
     Authorized redirect URI: ${WEB_BASE_URL}/connect/oauth/callback
  4. Copy client_id + secret into GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET.
  5. Enable the Gmail API in the project. (Calendar/Drive too if reused.)
  6. Until Google verifies the app, the user sees an "unverified app"
     warning — acceptable during alpha. Submit for verification before
     public launch.
"""
from __future__ import annotations

import base64
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


# Smallest useful scope set: read + send + modify (mark read, label, etc).
# Drop send and you can't reply on the user's behalf, which is half the
# point of a Gmail agent.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "openid",
    "email",
    "profile",
]


async def _gmail_get(
    path: str, access_token: str, params: dict | None = None
) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as c:
        r = await c.get(
            f"https://gmail.googleapis.com/gmail/v1{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            f"gmail GET {path} failed", status=r.status_code, body=r.text[:500]
        )
    return r.json()


async def _gmail_post(
    path: str, access_token: str, json: dict
) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as c:
        r = await c.post(
            f"https://gmail.googleapis.com/gmail/v1{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=json,
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            f"gmail POST {path} failed", status=r.status_code, body=r.text[:500]
        )
    return r.json()


# ── Tool callables ──────────────────────────────────────────────────────────


async def _list_threads(
    args: dict, conn: Connection, db: AsyncSession
) -> Any:
    token = (conn.config or {}).get("access_token")
    if not token:
        raise NativeOAuthError("gmail connection missing access_token")
    q = args.get("query") or ""
    max_results = min(int(args.get("max_results") or 20), 100)
    return await _gmail_get(
        "/users/me/threads",
        token,
        {"q": q, "maxResults": max_results},
    )


async def _get_message(
    args: dict, conn: Connection, db: AsyncSession
) -> Any:
    token = (conn.config or {}).get("access_token")
    msg_id = (args.get("message_id") or "").strip()
    if not msg_id:
        raise NativeOAuthError("message_id required")
    return await _gmail_get(
        f"/users/me/messages/{msg_id}",
        token,
        {"format": args.get("format") or "full"},
    )


async def _send_message(
    args: dict, conn: Connection, db: AsyncSession
) -> Any:
    """Send a Gmail message. Args: {to, subject, body, cc?, bcc?, in_reply_to?}.

    The Gmail API accepts raw RFC 2822, base64url-encoded. We compose minimal
    headers and trust the user-provided body. For HTML, the caller should
    set the body to a full multipart payload (v1 doesn't try to be smart
    about it)."""
    token = (conn.config or {}).get("access_token")
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = args.get("body") or ""
    if not to:
        raise NativeOAuthError("to is required")

    lines = [f"To: {to}", f"Subject: {subject}"]
    if args.get("cc"):
        lines.append(f"Cc: {args['cc']}")
    if args.get("bcc"):
        lines.append(f"Bcc: {args['bcc']}")
    if args.get("in_reply_to"):
        lines.append(f"In-Reply-To: {args['in_reply_to']}")
        lines.append(f"References: {args['in_reply_to']}")
    lines.append("Content-Type: text/plain; charset=utf-8")
    lines.append("")
    lines.append(body)
    raw = "\r\n".join(lines).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return await _gmail_post(
        "/users/me/messages/send",
        token,
        {"raw": encoded},
    )


# ── Handler ─────────────────────────────────────────────────────────────────


class GmailHandler(OAuthHandler):
    provider_slug = "gmail"
    display_provider = "gmail"
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    default_scopes = GMAIL_SCOPES
    scope_delimiter = " "
    # `access_type=offline` is what gives us a refresh_token; without
    # `prompt=consent` Google withholds the refresh on subsequent grants
    # if the user has already consented once.
    extra_auth_params = {
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }

    def client_id(self) -> str | None:
        return get_settings().gmail_client_id

    def client_secret(self) -> str | None:
        return get_settings().gmail_client_secret

    def tools(self) -> list[NativeToolSpec]:
        return [
            NativeToolSpec(
                name="gmail_list_threads",
                description=(
                    "Search Gmail and return matching threads. "
                    "`query` uses Gmail's search syntax (e.g. "
                    "'from:alice@acme.com is:unread')."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {
                            "type": "integer",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                },
                caller=_list_threads,
            ),
            NativeToolSpec(
                name="gmail_get_message",
                description="Fetch a single message by id, including headers + body.",
                input_schema={
                    "type": "object",
                    "required": ["message_id"],
                    "properties": {
                        "message_id": {"type": "string"},
                        "format": {
                            "type": "string",
                            "enum": ["minimal", "full", "raw", "metadata"],
                            "default": "full",
                        },
                    },
                },
                caller=_get_message,
            ),
            NativeToolSpec(
                name="gmail_send_message",
                description=(
                    "Send a plain-text email. TIER-2: requires "
                    "request_approval before invoking. Compose subject + body "
                    "before calling — the user sees these in the approval prompt."
                ),
                input_schema={
                    "type": "object",
                    "required": ["to", "subject", "body"],
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "cc": {"type": "string"},
                        "bcc": {"type": "string"},
                        "in_reply_to": {
                            "type": "string",
                            "description": "Message-ID header of the message being replied to.",
                        },
                    },
                },
                caller=_send_message,
            ),
        ]


_register(GmailHandler())
