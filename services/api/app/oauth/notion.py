"""Notion native OAuth handler.

Notion's OAuth issues a `bot_id`-scoped token that's good for the workspaces
the user explicitly selected during install. No refresh token — tokens are
long-lived (per Notion docs, no expiry). If a user revokes from Notion's
settings, our calls start 401-ing and they re-OAuth.

Setup (founder):
  1. notion.com/profile/integrations → New integration.
  2. Choose "Public integration" (vs Internal — Public is what white-labels).
  3. OAuth Authorization URL → Add redirect:
       ${WEB_BASE_URL}/connect/oauth/callback
  4. Secrets → copy OAuth client ID + secret → NOTION_CLIENT_ID /
     NOTION_CLIENT_SECRET.
  5. Capabilities: read content + insert content + update content + comments.

Auth nuance: Notion's token endpoint uses HTTP Basic auth (client_id +
client_secret) instead of POST body params. The base handler posts in
body form, so we override `handle_callback` to do Basic auth.
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
    decode_state,
)


log = logging.getLogger(__name__)


NOTION_VERSION = "2022-06-28"


async def _notion_post(path: str, token: str, json: dict) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.post(
            f"https://api.notion.com/v1{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            json=json,
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            f"notion POST {path} failed", status=r.status_code, body=r.text[:500]
        )
    return r.json()


async def _notion_get(path: str, token: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.get(
            f"https://api.notion.com/v1{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
            },
            params=params or {},
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            f"notion GET {path} failed", status=r.status_code, body=r.text[:500]
        )
    return r.json()


# ── Tool callables ──────────────────────────────────────────────────────────


async def _search(args: dict, conn: Connection, db: AsyncSession) -> Any:
    token = (conn.config or {}).get("access_token")
    body: dict[str, Any] = {
        "page_size": min(int(args.get("page_size") or 20), 100),
    }
    if args.get("query"):
        body["query"] = args["query"]
    if args.get("filter_type"):
        body["filter"] = {"value": args["filter_type"], "property": "object"}
    return await _notion_post("/search", token, body)


async def _get_page(args: dict, conn: Connection, db: AsyncSession) -> Any:
    token = (conn.config or {}).get("access_token")
    page_id = (args.get("page_id") or "").strip()
    if not page_id:
        raise NativeOAuthError("page_id required")
    page = await _notion_get(f"/pages/{page_id}", token)
    blocks = await _notion_get(
        f"/blocks/{page_id}/children", token, {"page_size": 100}
    )
    return {"page": page, "blocks": blocks}


# ── Handler ─────────────────────────────────────────────────────────────────


class NotionHandler(OAuthHandler):
    provider_slug = "notion"
    display_provider = "notion"
    authorize_url = "https://api.notion.com/v1/oauth/authorize"
    token_url = "https://api.notion.com/v1/oauth/token"
    default_scopes: list[str] = []  # Notion derives scope from app capabilities
    scope_delimiter = " "
    extra_auth_params = {"owner": "user"}

    def client_id(self) -> str | None:
        return get_settings().notion_client_id

    def client_secret(self) -> str | None:
        return get_settings().notion_client_secret

    async def handle_callback(
        self, *, code: str, state: str, db: AsyncSession
    ) -> Connection:
        """Override because Notion's token endpoint takes Basic auth, not
        form-encoded client creds in the body."""
        payload = decode_state(state)
        from uuid import UUID
        org_id = UUID(payload["o"])
        agent_id = UUID(payload["a"]) if payload.get("a") else None

        cid = self.client_id()
        secret = self.client_secret()
        if not cid or not secret:
            raise NativeOAuthError("notion OAuth credentials missing")

        basic = base64.b64encode(f"{cid}:{secret}".encode("utf-8")).decode("ascii")
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
            r = await c.post(
                self.token_url,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Notion-Version": NOTION_VERSION,
                },
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri(),
                },
            )
        if r.status_code >= 400:
            raise NativeOAuthError(
                "notion token exchange failed",
                status=r.status_code,
                body=r.text[:500],
            )
        tok = r.json()
        return await self._upsert_connection(
            db=db,
            org_id=org_id,
            agent_id=agent_id,
            token=tok,
        )

    def tools(self) -> list[NativeToolSpec]:
        return [
            NativeToolSpec(
                name="notion_search",
                description=(
                    "Search Notion pages and databases the integration has "
                    "access to. Returns up to `page_size` results."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "page_size": {"type": "integer", "default": 20},
                        "filter_type": {
                            "type": "string",
                            "enum": ["page", "database"],
                        },
                    },
                },
                caller=_search,
            ),
            NativeToolSpec(
                name="notion_get_page",
                description=(
                    "Fetch a Notion page's metadata + its top-level block "
                    "children (one level deep). Use repeated calls for deep "
                    "trees."
                ),
                input_schema={
                    "type": "object",
                    "required": ["page_id"],
                    "properties": {"page_id": {"type": "string"}},
                },
                caller=_get_page,
            ),
        ]


_register(NotionHandler())
