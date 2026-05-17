"""HubSpot native OAuth handler.

HubSpot's OAuth2 + REST. Tokens last 30 min (access) and forever (refresh)
until revoked. Setup:

  1. developers.hubspot.com → Create app.
  2. Auth → Redirect URL: ${WEB_BASE_URL}/connect/oauth/callback
  3. Scopes: at minimum `crm.objects.contacts.read`, `crm.objects.deals.read`,
     `crm.objects.contacts.write`. Add more as the tool surface grows.
  4. Copy client_id + secret into HUBSPOT_CLIENT_ID / HUBSPOT_CLIENT_SECRET.
  5. Install URL Aki generates includes the hub the user picks during
     consent → `hub_id` is returned in the token response and stored on
     the Connection.
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


HUBSPOT_SCOPES = [
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.deals.read",
    "oauth",
]


async def _hubspot_get(path: str, token: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.get(
            f"https://api.hubapi.com{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            f"hubspot GET {path} failed", status=r.status_code, body=r.text[:500]
        )
    return r.json()


async def _hubspot_post(path: str, token: str, json: dict) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.post(
            f"https://api.hubapi.com{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=json,
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            f"hubspot POST {path} failed", status=r.status_code, body=r.text[:500]
        )
    return r.json()


# ── Tool callables ──────────────────────────────────────────────────────────


async def _list_contacts(args: dict, conn: Connection, db: AsyncSession) -> Any:
    token = (conn.config or {}).get("access_token")
    return await _hubspot_get(
        "/crm/v3/objects/contacts",
        token,
        {
            "limit": min(int(args.get("limit") or 25), 100),
            "properties": "firstname,lastname,email,phone,company,lifecyclestage",
        },
    )


async def _list_deals(args: dict, conn: Connection, db: AsyncSession) -> Any:
    token = (conn.config or {}).get("access_token")
    return await _hubspot_get(
        "/crm/v3/objects/deals",
        token,
        {
            "limit": min(int(args.get("limit") or 25), 100),
            "properties": "dealname,amount,dealstage,closedate,pipeline",
        },
    )


async def _create_contact(args: dict, conn: Connection, db: AsyncSession) -> Any:
    """TIER-2: writing to a customer's CRM is irreversible-ish."""
    token = (conn.config or {}).get("access_token")
    email = (args.get("email") or "").strip()
    if not email:
        raise NativeOAuthError("email is required")
    props: dict[str, Any] = {"email": email}
    for k in ("firstname", "lastname", "phone", "company", "lifecyclestage"):
        if args.get(k):
            props[k] = args[k]
    return await _hubspot_post(
        "/crm/v3/objects/contacts", token, {"properties": props}
    )


# ── Handler ─────────────────────────────────────────────────────────────────


class HubSpotHandler(OAuthHandler):
    provider_slug = "hubspot"
    display_provider = "hubspot"
    authorize_url = "https://app.hubspot.com/oauth/authorize"
    token_url = "https://api.hubapi.com/oauth/v1/token"
    default_scopes = HUBSPOT_SCOPES
    scope_delimiter = " "

    def client_id(self) -> str | None:
        return get_settings().hubspot_client_id

    def client_secret(self) -> str | None:
        return get_settings().hubspot_client_secret

    def tools(self) -> list[NativeToolSpec]:
        return [
            NativeToolSpec(
                name="hubspot_list_contacts",
                description="List CRM contacts. Returns up to `limit` (default 25, max 100).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 25},
                    },
                },
                caller=_list_contacts,
            ),
            NativeToolSpec(
                name="hubspot_list_deals",
                description="List CRM deals. Returns up to `limit` (default 25).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 25},
                    },
                },
                caller=_list_deals,
            ),
            NativeToolSpec(
                name="hubspot_create_contact",
                description=(
                    "Create a new CRM contact. TIER-2: request_approval "
                    "before writing — duplicate-on-email is HubSpot's default "
                    "behavior so re-runs may noop, but the agent should still "
                    "ask first."
                ),
                input_schema={
                    "type": "object",
                    "required": ["email"],
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "firstname": {"type": "string"},
                        "lastname": {"type": "string"},
                        "phone": {"type": "string"},
                        "company": {"type": "string"},
                        "lifecyclestage": {"type": "string"},
                    },
                },
                caller=_create_contact,
            ),
        ]


_register(HubSpotHandler())
