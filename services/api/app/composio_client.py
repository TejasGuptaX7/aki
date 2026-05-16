"""Thin async wrapper around Composio's v3 HTTP API.

All endpoint paths and field names below are confirmed against the live
backend.composio.dev/api/v3/openapi.json spec and tested with real calls.

Concepts:
- A Composio **user_id** is whatever identifier we choose for the end user; we
  use the Aki organization_id (uuid). One Composio user-namespace per org.
- A **connected_account** (`ca_…`) is one OAuth grant — e.g. "this org's Gmail
  account." Created via the link flow.
- An **auth_config** (`ac_…`) is the OAuth app configuration for a toolkit
  (e.g. "Gmail OAuth2, Composio-managed"). Pre-created in the Composio dashboard;
  ID lives in settings.
- A **tool_router session** (`trs_…`) is what `composio.create(userId)` returns
  in the TS SDK — a stateful MCP endpoint that automatically surfaces tools for
  all of the user's active connected_accounts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class OAuthLink:
    redirect_url: str
    connected_account_id: str           # ca_…
    link_token: str
    expires_at: str


@dataclass(frozen=True)
class ConnectionState:
    id: str                             # ca_…
    user_id: str
    status: str                         # INITIALIZING | ACTIVE | FAILED | …
    toolkit_slug: str                   # gmail
    auth_config_id: str                 # ac_…


@dataclass(frozen=True)
class ToolRouterSession:
    session_id: str                     # trs_…
    mcp_url: str
    mcp_type: str                       # "http"


class ComposioClient:
    def __init__(self) -> None:
        s = get_settings()
        self._api_key = s.composio_api_key
        self._base = s.composio_base_url.rstrip("/")
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise RuntimeError("COMPOSIO_API_KEY not configured")
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    async def create_tool_router_session(
        self, user_id: UUID
    ) -> ToolRouterSession:
        """Equivalent of `composio.create(userId)` in the TS SDK.

        Returns the MCP URL + type to drop into hermes.config.yaml's
        mcp.servers[]. The session is stateful: it picks up newly-connected
        accounts for the same user_id automatically.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{self._base}/api/v3/tool_router/session",
                headers=self._headers(),
                json={"user_id": str(user_id)},
            )
            r.raise_for_status()
            d = r.json()
            mcp = d["mcp"]
            return ToolRouterSession(
                session_id=d["session_id"],
                mcp_url=mcp["url"],
                mcp_type=mcp.get("type", "http"),
            )

    async def initiate_oauth(
        self,
        user_id: UUID,
        auth_config_id: str,
        callback_url: str,
    ) -> OAuthLink:
        """Create an auth-link session. The returned redirect_url is the
        Composio-hosted OAuth page; user authorizes there and Composio redirects
        them to callback_url with the connected_account_id wired through."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{self._base}/api/v3/connected_accounts/link",
                headers=self._headers(),
                json={
                    "auth_config_id": auth_config_id,
                    "user_id": str(user_id),
                    "callback_url": callback_url,
                },
            )
            r.raise_for_status()
            d = r.json()
            return OAuthLink(
                redirect_url=d["redirect_url"],
                connected_account_id=d["connected_account_id"],
                link_token=d["link_token"],
                expires_at=d["expires_at"],
            )

    async def get_connection(self, connected_account_id: str) -> ConnectionState:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(
                f"{self._base}/api/v3/connected_accounts/{connected_account_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            d = r.json()
            return ConnectionState(
                id=d["id"],
                user_id=d["user_id"],
                status=(d.get("status") or "INITIALIZING").upper(),
                toolkit_slug=(d.get("toolkit") or {}).get("slug", "unknown"),
                auth_config_id=(d.get("auth_config") or {}).get("id", ""),
            )

    async def revoke(self, connected_account_id: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.delete(
                f"{self._base}/api/v3/connected_accounts/{connected_account_id}",
                headers=self._headers(),
            )
            r.raise_for_status()


def get_composio_client() -> ComposioClient:
    return ComposioClient()


# Provider name → settings attribute holding the Composio Auth Config ID.
# Add a new entry here when you enable a new toolkit in the Composio dashboard.
_AUTH_CONFIG_BY_PROVIDER = {
    "gmail": "composio_gmail_auth_config_id",
}


def auth_config_id_for(provider: str) -> str:
    s = get_settings()
    attr = _AUTH_CONFIG_BY_PROVIDER.get(provider)
    if attr is None:
        raise ValueError(f"no Composio auth_config_id mapping for provider={provider!r}")
    value = getattr(s, attr, None)
    if not value:
        raise RuntimeError(
            f"{attr.upper()} not configured — create the auth config in Composio "
            "dashboard and add its ID to .env"
        )
    return value
