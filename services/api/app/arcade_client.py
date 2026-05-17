"""Arcade.dev API client.

Arcade gives us first-class agent-auth ("URL Elicitation") for the top-20
high-value tools — Gmail send, Slack post, Calendar, Linear, etc. The agent
asks the user for permission mid-task, gets back a scoped token, acts. This
is a tighter loop than Pipedream's "pre-connect everything you'll need" model.

Auth model is dirt-simple: a static project-scoped API key (`arc_proj_xxx`)
sent as `Authorization: Bearer <key>` on every call. No JWT exchange, no
env header. Project scope is encoded in the key itself.

What this client exposes:
  - `start_auth(user_id, provider)` — begin the URL Elicitation flow
  - `check_auth(auth_id)` — poll the flow's status; returns the token id
    once authorized
  - `list_tools()` — catalogue we surface to Hermes
  - `mcp_url()` and `mcp_headers()` — what materialize.py drops into the
    per-agent config so Hermes can call Arcade tools as MCP

Arcade's REST docs: https://docs.arcade.dev/api-reference/

Things this client deliberately does NOT do:
  - Cache the API key (it's already static; no cache needed)
  - Cache tool lists / auth statuses (data is small + fresh-on-call is fine)
  - Sign webhooks (not used yet)
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings


log = logging.getLogger(__name__)


class ArcadeError(RuntimeError):
    def __init__(self, msg: str, *, status: int = 0, body: str = ""):
        super().__init__(msg)
        self.status = status
        self.body = body


def _require(name: str, value: str | None) -> str:
    if not value:
        raise RuntimeError(f"{name} not configured; Arcade client cannot run")
    return value


class ArcadeClient:
    def __init__(self) -> None:
        s = get_settings()
        self._api_key = _require("ARCADE_API_KEY", s.arcade_api_key)
        self._base = s.arcade_base_url.rstrip("/")
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        expect: tuple[int, ...] = (200, 201, 204),
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.request(
                method,
                f"{self._base}{path}",
                headers=self._headers(),
                json=json,
                params=params,
            )
        if r.status_code not in expect:
            raise ArcadeError(
                f"arcade {method} {path} failed",
                status=r.status_code,
                body=r.text[:500],
            )
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    # ── Auth (URL Elicitation flow) ────────────────────────────────────────

    async def start_auth(
        self,
        user_id: str,
        provider: str,
        *,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start the URL Elicitation auth flow. Returns
        `{auth_id, auth_url, status: "pending"}`. The frontend redirects
        the user to auth_url; Arcade handles consent + redirect back to a
        configured return URL.

        `user_id` is our identifier (org UUID, or `org_id:agent_id` for
        per-agent scoping). Arcade tracks one Arcade user per unique value.
        """
        body: dict[str, Any] = {"user_id": user_id, "provider": provider}
        if scopes:
            body["scopes"] = scopes
        return await self._request("POST", "/v1/auth/start", json=body)

    async def check_auth(self, auth_id: str) -> dict[str, Any]:
        """Poll an auth flow's status. Returns
        `{status: "pending|authorized|denied|expired", token_id?: str}`.

        Once `status == "authorized"`, the returned `token_id` is what
        Hermes uses to call Arcade tools as that user."""
        return await self._request("GET", f"/v1/auth/status/{auth_id}")

    # ── Tool catalogue ─────────────────────────────────────────────────────

    async def list_tools(
        self,
        *,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Arcade tools available to our project. Optionally filter to
        one provider (gmail, slack, ...) for the connections UI."""
        params: dict[str, str] = {}
        if provider:
            params["provider"] = provider
        d = await self._request("GET", "/v1/tools", params=params)
        return d.get("data") or d.get("tools") or []

    # ── MCP integration ────────────────────────────────────────────────────
    #
    # Arcade exposes an MCP endpoint per project; the per-user scoping
    # happens via a header carrying the Arcade user_id (and Arcade looks up
    # that user's authorized token_ids internally).

    def mcp_url(self) -> str:
        return f"{self._base}/v1/mcp"

    def mcp_headers(self, user_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Arcade-User-Id": user_id,
        }


_singleton: ArcadeClient | None = None


def get_arcade_client() -> ArcadeClient:
    """Lazy singleton. Raises if API key missing — callers should catch and
    skip Arcade integration if not configured."""
    global _singleton
    if _singleton is None:
        _singleton = ArcadeClient()
    return _singleton
