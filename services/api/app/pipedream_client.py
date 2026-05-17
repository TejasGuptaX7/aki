"""Pipedream Connect API client.

Auth model: OAuth2 `client_credentials` exchange against
`POST /v1/oauth/token` returns a short-lived JWT (~60 min). We cache it
with single-flight refresh; the cache key is implicit — one set of
credentials per process.

Every Connect API call carries:

    Authorization: Bearer <JWT>
    X-PD-Environment: development | production

Why the env header exists: Pipedream Connect has separate `development`
and `production` namespaces per project. Dev orgs and prod orgs see
different connected accounts. We source the env from
`settings.pipedream_environment` and treat it as static per-process — the
dev API instance always talks to `development`, the prod instance always
to `production`.

Things this client deliberately does NOT do:
  - Sign Pipedream Connect webhooks. That's a separate `signing_secret`
    living in the project dashboard; we'll add it when we add `/webhooks/pipedream`.
  - Cache anything besides the JWT. Account lists / tool catalogues come
    fresh on every call; Pipedream's data plane is fast enough that the
    cache wouldn't pay for the staleness risk.
  - Auto-paginate beyond what `list_accounts` does. If we need more,
    add as we go.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


log = logging.getLogger(__name__)


@dataclass
class _CachedJWT:
    token: str
    expires_at: float          # unix ts


_jwt_cache: _CachedJWT | None = None
_jwt_lock = asyncio.Lock()

# Refresh this many seconds before the actual expiry so in-flight requests
# don't race the refresh boundary. Generous given the typical 1h lifetime.
_REFRESH_BUFFER_S = 60.0


class PipedreamError(RuntimeError):
    """API call failed. `.status` is the HTTP status (0 if not networked).
    `.body` is the upstream response body (truncated)."""

    def __init__(self, msg: str, *, status: int = 0, body: str = ""):
        super().__init__(msg)
        self.status = status
        self.body = body


def _require(name: str, value: str | None) -> str:
    if not value:
        raise RuntimeError(f"{name} not configured; Pipedream client cannot run")
    return value


class PipedreamClient:
    def __init__(self) -> None:
        s = get_settings()
        self._client_id = _require("PIPEDREAM_CLIENT_ID", s.pipedream_client_id)
        self._client_secret = _require("PIPEDREAM_CLIENT_SECRET", s.pipedream_client_secret)
        self._project_id = _require("PIPEDREAM_PROJECT_ID", s.pipedream_project_id)
        self._environment = s.pipedream_environment
        self._base = s.pipedream_base_url.rstrip("/")
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ── JWT ────────────────────────────────────────────────────────────────

    async def _jwt(self) -> str:
        global _jwt_cache
        now = time.time()
        cached = _jwt_cache
        if cached and cached.expires_at - _REFRESH_BUFFER_S > now:
            return cached.token

        async with _jwt_lock:
            # Re-check under lock — another coroutine may have refreshed.
            cached = _jwt_cache
            if cached and cached.expires_at - _REFRESH_BUFFER_S > now:
                return cached.token

            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(
                    f"{self._base}/v1/oauth/token",
                    headers={"Content-Type": "application/json"},
                    json={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
            if r.status_code != 200:
                raise PipedreamError(
                    "pipedream OAuth failed",
                    status=r.status_code,
                    body=r.text[:500],
                )
            d = r.json()
            token = d["access_token"]
            expires_in = int(d.get("expires_in") or 3600)
            _jwt_cache = _CachedJWT(token=token, expires_at=now + expires_in)
            return token

    # ── Connect API helpers ────────────────────────────────────────────────

    def _connect_url(self, *parts: str) -> str:
        return "/".join([self._base, "v1", "connect", self._project_id, *parts])

    async def _connect_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._jwt()}",
            "X-PD-Environment": self._environment,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        expect: tuple[int, ...] = (200, 201, 204),
    ) -> dict[str, Any]:
        """Generic Connect-authenticated request. Returns parsed JSON, or
        an empty dict for 204."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.request(
                method,
                url,
                headers=await self._connect_headers(),
                json=json,
                params=params,
            )
        if r.status_code not in expect:
            raise PipedreamError(
                f"pipedream {method} {url} failed",
                status=r.status_code,
                body=r.text[:500],
            )
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    # ── Public methods ─────────────────────────────────────────────────────

    async def create_connect_token(
        self,
        external_user_id: str,
        *,
        allowed_origins: list[str] | None = None,
        success_redirect_uri: str | None = None,
        error_redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        """Create a Connect Token the frontend uses to initiate OAuth via
        Pipedream's JS SDK. The token authorizes ONE end-user to connect
        accounts under our project.

        `external_user_id` is the identifier we choose — we use the org UUID
        (with optional `:agent_id` suffix when we want per-agent scoping).
        Pipedream creates an entity per unique value the first time it sees
        one and tracks all connected accounts under it.
        """
        body: dict[str, Any] = {"external_user_id": external_user_id}
        if allowed_origins is not None:
            body["allowed_origins"] = allowed_origins
        if success_redirect_uri is not None:
            body["success_redirect_uri"] = success_redirect_uri
        if error_redirect_uri is not None:
            body["error_redirect_uri"] = error_redirect_uri
        return await self._request("POST", self._connect_url("tokens"), json=body)

    async def list_accounts(
        self,
        *,
        external_user_id: str | None = None,
        app: str | None = None,
    ) -> list[dict[str, Any]]:
        """List connected accounts in this project + environment. Filter
        by external_user_id (one user's accounts) and/or app (one toolkit
        across all users). Walks cursor pagination until exhausted."""
        params: dict[str, str] = {}
        if external_user_id:
            params["external_user_id"] = external_user_id
        if app:
            params["app"] = app

        results: list[dict[str, Any]] = []
        url: str | None = self._connect_url("accounts")
        first = True
        while url:
            d = await self._request(
                "GET", url, params=params if first else None
            )
            results.extend(d.get("data") or [])
            next_url = (d.get("page_info") or {}).get("next_url")
            url = next_url
            first = False
        return results

    async def get_account(self, account_id: str) -> dict[str, Any]:
        d = await self._request("GET", self._connect_url("accounts", account_id))
        return d.get("data", d)

    async def delete_account(self, account_id: str) -> None:
        await self._request(
            "DELETE",
            self._connect_url("accounts", account_id),
            expect=(200, 204),
        )

    # ── MCP integration ────────────────────────────────────────────────────
    #
    # Pipedream Connect exposes one MCP endpoint per (project, external_user)
    # that surfaces tools for ALL the user's connected accounts. We give
    # Hermes that URL plus the auth headers; tool discovery and execution
    # happen inside Hermes.
    #
    # JWT lifecycle wart: Hermes loads its mcp_servers config once at
    # profile start and doesn't refresh headers mid-conversation. With our
    # 15-min hibernation and 60-min JWT lifetime that's typically fine
    # (next cold-start reloads). The edge case is a single chat session
    # >60min without hibernation — JWT expires mid-session. v2 fix: stand
    # up a per-org MCP proxy that injects a fresh JWT per call. v1: accept
    # the rare retry.

    def mcp_url(self, external_user_id: str) -> str:
        return f"{self._base}/v1/connect/{self._project_id}/mcp/{external_user_id}"

    async def mcp_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._jwt()}",
            "X-PD-Environment": self._environment,
        }


_singleton: PipedreamClient | None = None


def get_pipedream_client() -> PipedreamClient:
    """Lazy singleton. Raises if creds missing — callers should catch and
    skip Pipedream integration when not configured (e.g. local dev without
    pipedream env vars set)."""
    global _singleton
    if _singleton is None:
        _singleton = PipedreamClient()
    return _singleton
