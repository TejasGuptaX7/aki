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
        toolkit_slug: str,
        callback_url: str,
        auth_config_id: str | None = None,
    ) -> OAuthLink:
        """Create an OAuth link scoped to this user's tool_router session.

        Passing `auth_config_id` forces Composio to use OUR registered
        Slack app (e.g. the branded "Aki" one) instead of falling back to
        a Composio-managed default. Without it the tool_router silently
        creates its own managed config — that's why bots installed as
        "Composio" instead of "Aki" before this fix.

        The session-scoped link (not the legacy /connected_accounts/link)
        is required so the resulting connection is visible to the same
        agent session that COMPOSIO_MANAGE_CONNECTIONS would create.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            # Resolve the user's tool_router session — idempotent server-side.
            sess_r = await c.post(
                f"{self._base}/api/v3/tool_router/session",
                headers=self._headers(),
                json={"user_id": str(user_id)},
            )
            sess_r.raise_for_status()
            sid = sess_r.json()["session_id"]

            body: dict[str, Any] = {
                "toolkit": toolkit_slug,
                "callback_url": callback_url,
            }
            if auth_config_id:
                body["auth_config_id"] = auth_config_id

            r = await c.post(
                f"{self._base}/api/v3/tool_router/session/{sid}/link",
                headers=self._headers(),
                json=body,
            )
            r.raise_for_status()
            d = r.json()
            return OAuthLink(
                redirect_url=d["redirect_url"],
                connected_account_id=d["connected_account_id"],
                link_token=d["link_token"],
                expires_at=d.get("expires_at", ""),
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

    async def execute_action(
        self,
        user_id: UUID,
        action_slug: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a Composio action server-side, without going through Hermes.

        Used by Brain's live-ACL recheck so we can verify channel/page
        permissions without paying the cold-start of the per-dept agent.

        action_slug is the canonical Composio action id, e.g.
        "SLACK_FETCH_CONVERSATION_INFO".
        """
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{self._base}/api/v3/actions/{action_slug}/execute",
                headers=self._headers(),
                json={"user_id": str(user_id), "arguments": arguments},
            )
            r.raise_for_status()
            return r.json()


def get_composio_client() -> ComposioClient:
    return ComposioClient()


# auth_config_id is no longer required for /connect — we use the
# session-scoped link endpoint which works off toolkit slug. The settings
# entries are kept around for any future need (e.g. enforcing a specific
# auth_config), but `auth_config_id_for` is now a no-op lookup that returns
# None when unset.
_AUTH_CONFIG_BY_PROVIDER = {
    "gmail": "composio_gmail_auth_config_id",
    "slack": "composio_slack_auth_config_id",
    "slackbot": "composio_slackbot_auth_config_id",
}


def auth_config_id_for(provider: str) -> str | None:
    s = get_settings()
    attr = _AUTH_CONFIG_BY_PROVIDER.get(provider)
    return getattr(s, attr, None) if attr else None
