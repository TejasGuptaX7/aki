"""Arcade.dev REST API client.

Arcade is our long-tail connector platform — it ships managed adapters for
~50 SaaS apps via a single MCP gateway, and handles the OAuth dance per
provider. For the top-5 high-value providers (Gmail, Slack, Notion, Linear,
HubSpot) we own the OAuth flow ourselves (see app/oauth/). Arcade picks up
everything else.

White-label model:
  1. We bring our own OAuth client credentials per provider via
     `POST /v1/admin/auth_providers` (or via the Arcade dashboard at
     setup time).
  2. Arcade's MCP gateway URL — `https://api.arcade.dev/mcp/<slug>` — is
     handed to Hermes as one MCP server entry per (project, end-user).
  3. Per-end-user identity rides on the `Arcade-User-ID` header. We use
     our org UUID (or `org_id:agent_id` when per-agent scoping).
  4. Optional custom user verifier: Arcade calls back to our
     /oauth/arcade/verifier endpoint to confirm a session is still valid
     before issuing a token. Wired up in routes/oauth_verifier.py.

Auth model is a static project-scoped API key (`arc_proj_xxx`) sent as
`Authorization: Bearer <key>`. No JWT exchange, no env header.

Endpoint reference (from `https://api.arcade.dev/v1/swagger`):
  POST  /v1/auth/authorize             — initiate auth flow
  GET   /v1/auth/status?id=…&wait=…    — poll auth status (long-poll up to 59s)
  GET   /v1/tools                      — list available tools
  POST  /v1/tools/execute              — execute a tool
  POST  /v1/admin/auth_providers       — register OAuth client creds
  POST  /v1/auth/validate_custom_verifier — test our verifier endpoint
  GET   /mcp/<gateway-slug>            — Streamable HTTP MCP gateway

Things this client deliberately does NOT do:
  - Cache the API key (already static)
  - Sign incoming webhooks (handled in routes/oauth_verifier.py with the
    `arcade_verifier_token` shared secret)
  - Provision auth providers at boot — we treat dashboard config as the
    source of truth for OAuth credentials. `register_auth_provider()` is
    available for scripted setup but no caller invokes it on startup.
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
        self._gateway_slug = s.arcade_mcp_gateway_slug
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
        params: dict[str, Any] | None = None,
        expect: tuple[int, ...] = (200, 201, 204),
        timeout: float | None = None,
    ) -> dict[str, Any]:
        t = httpx.Timeout(timeout, connect=5.0) if timeout else self._timeout
        async with httpx.AsyncClient(timeout=t) as c:
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

    # ── Auth flow (URL Elicitation) ────────────────────────────────────────

    async def start_auth(
        self,
        user_id: str,
        provider_id: str,
        *,
        scopes: list[str] | None = None,
        next_uri: str | None = None,
    ) -> dict[str, Any]:
        """Start an authorization flow against a configured Arcade auth
        provider. `provider_id` is the dashboard-assigned identifier (e.g.
        "aki-google" if we registered our Google OAuth client there).

        Returns the raw AuthorizationResponse: `{id, url, status, provider_id,
        scopes, context, user_id}`. Caller redirects the user to `url` and
        polls `poll_auth_status(id)` for completion.
        """
        oauth_req: dict[str, Any] = {}
        if scopes:
            oauth_req["scopes"] = scopes

        body: dict[str, Any] = {
            "user_id": user_id,
            "auth_requirement": {
                "provider_id": provider_id,
                "oauth2": oauth_req,
            },
        }
        if next_uri:
            body["next_uri"] = next_uri
        return await self._request("POST", "/v1/auth/authorize", json=body)

    async def poll_auth_status(
        self,
        auth_id: str,
        *,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        """Get an authorization's current status. With `wait_seconds > 0`
        Arcade long-polls server-side and returns as soon as the status
        changes (max 59s per the spec).

        Returns `{id, status: "not_started|pending|completed|failed", url,
        context: {token, user_info}, ...}`.
        """
        # Cap to Arcade's documented max of 59s.
        wait = max(0, min(59, int(wait_seconds)))
        params: dict[str, Any] = {"id": auth_id}
        if wait > 0:
            params["wait"] = wait
        return await self._request(
            "GET",
            "/v1/auth/status",
            params=params,
            timeout=max(self._timeout.read or 15.0, wait + 5.0),
        )

    # ── Custom user verifier ───────────────────────────────────────────────

    async def validate_custom_verifier(
        self, user_id: str, verifier_url: str
    ) -> dict[str, Any]:
        """Trigger Arcade's end-to-end test of our contextual-access webhook.

        Arcade POSTs to `<verifier_url>/access` (or `/pre`) with a synthetic
        payload using `user_id`; the response tells us whether our verifier
        is correctly signed, reachable, and returning the right shape. Use
        for smoke tests after spinning up routes/oauth_verifier.py.
        """
        return await self._request(
            "POST",
            "/v1/auth/validate_custom_verifier",
            json={"user_id": user_id, "verifier_url": verifier_url},
        )

    # ── Auth provider registration (white-label OAuth creds) ───────────────

    async def register_auth_provider(
        self,
        *,
        id: str,
        provider_type: str,
        client_id: str,
        client_secret: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Register our own OAuth client credentials so the consent screen
        shows OUR brand instead of Arcade's. `provider_type` is one of the
        built-in slugs ("google", "slack", "notion", "linear", "hubspot",
        ...) — see https://docs.arcade.dev/en/references/auth-providers.

        `id` is OUR unique label (e.g. "aki-google"). That id is what we
        pass as `provider_id` to start_auth().

        Idempotent on the dashboard side: re-running with a duplicate id
        returns the existing provider (Arcade 409s; caller should ignore
        or catch).
        """
        body: dict[str, Any] = {
            "id": id,
            "type": provider_type,
            "oauth2": {
                "client_id": client_id,
                "client_secret": client_secret,
            },
        }
        if description:
            body["description"] = description
        return await self._request(
            "POST",
            "/v1/admin/auth_providers",
            json=body,
            expect=(200, 201),
        )

    # ── Tool catalogue ─────────────────────────────────────────────────────

    async def list_tools(
        self,
        *,
        toolkit: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Arcade tools available to our project. Optionally filter to
        one toolkit (e.g. "calendar", "drive")."""
        params: dict[str, str] = {}
        if toolkit:
            params["toolkit"] = toolkit
        d = await self._request("GET", "/v1/tools", params=params)
        return d.get("items") or d.get("data") or []

    # ── MCP integration ────────────────────────────────────────────────────
    #
    # Arcade hosts one MCP gateway per project/configured-gateway. The
    # gateway URL is `https://api.arcade.dev/mcp/<gateway-slug>`. Per-user
    # scoping rides on the `Arcade-User-ID` request header; Arcade looks up
    # the matching authorized tokens internally and injects them on tool
    # execution.

    def mcp_url(self) -> str:
        if not self._gateway_slug:
            raise RuntimeError(
                "ARCADE_MCP_GATEWAY_SLUG not configured; "
                "Arcade MCP integration cannot be materialized"
            )
        return f"{self._base}/mcp/{self._gateway_slug}"

    def mcp_headers(self, user_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Arcade-User-ID": user_id,
        }


_singleton: ArcadeClient | None = None


def get_arcade_client() -> ArcadeClient:
    """Lazy singleton. Raises if API key missing — callers should catch and
    skip Arcade integration if not configured."""
    global _singleton
    if _singleton is None:
        _singleton = ArcadeClient()
    return _singleton
