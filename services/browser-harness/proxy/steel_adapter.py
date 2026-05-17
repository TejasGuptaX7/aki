"""Steel.dev REST + CDP adapter.

See PROTOCOL_v2.md §3 for the routing decision. This module owns
*only* the vendor wire shape — no MCP, no profile bookkeeping (that's
profile_store.py), no CDP driving (that's cdp.py).

Steel docs reference:
  REST: https://api.steel.dev (auth header: `steel-api-key`)
  CDP WS: wss://connect.steel.dev?apiKey=…&sessionId=… (no `connectUrl`
          field in REST response; the URL is constructed client-side)
  Profiles: server-side persistence (300 MB cap, 30-day TTL when idle).
            Created via POST /v1/profiles, attached via `profileId` on
            session create.

The REST surface is small enough that we hit it directly with aiohttp
instead of pulling the Steel SDK (one fewer transitive deps tree, and
the SDK pins a specific httpx major that conflicts with our boto3 chain
in some envs).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

STEEL_API_BASE = os.environ.get("STEEL_API_BASE", "https://api.steel.dev").rstrip("/")
STEEL_CDP_BASE = os.environ.get("STEEL_CDP_BASE", "wss://connect.steel.dev").rstrip("/")


class SteelError(Exception):
    """Raised when Steel rejects a call. .status holds the HTTP code if any."""

    def __init__(self, message: str, status: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class SteelSession:
    session_id: str
    cdp_ws_url: str
    profile_id: Optional[str]
    viewer_url: Optional[str]


class SteelAdapter:
    """One adapter instance per server process. Holds the API key + a
    long-lived aiohttp ClientSession (kept open for the process
    lifetime to amortise TLS)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("STEEL_API_KEY")
        self._http: Optional[aiohttp.ClientSession] = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def start(self) -> None:
        if not self.enabled:
            log.warning("steel_disabled — set STEEL_API_KEY to enable Steel routing")
            return
        self._http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"steel-api-key": self.api_key, "Content-Type": "application/json"},
        )
        log.info("steel_adapter_started base=%s", STEEL_API_BASE)

    async def stop(self) -> None:
        if self._http:
            await self._http.close()
            self._http = None

    # ---- profiles --------------------------------------------------------

    async def create_profile(self, *, user_agent: Optional[str] = None) -> str:
        """POST /v1/profiles → returns profile id.

        Docs only show the SDK signature (client.profiles.create(...))
        so the body shape here is conservative — empty body is accepted;
        userAgent is optional. If Steel's REST surface diverges in
        practice the failure mode is a clean 4xx with a Steel error
        message; surfaces as SteelError with status."""
        body: dict = {}
        if user_agent:
            body["userAgent"] = user_agent
        data = await self._request("POST", "/v1/profiles", json=body)
        pid = data.get("id") or data.get("profileId")
        if not pid:
            raise SteelError(
                f"create_profile: response missing id field: {data!r}"
            )
        return pid

    async def delete_profile(self, profile_id: str) -> bool:
        try:
            await self._request("DELETE", f"/v1/profiles/{quote(profile_id, safe='')}")
            return True
        except SteelError as e:
            if e.status == 404:
                return False
            raise

    # ---- sessions --------------------------------------------------------

    async def create_session(
        self,
        *,
        profile_id: Optional[str] = None,
        timeout_seconds: int = 900,
        solve_captcha: bool = False,
    ) -> SteelSession:
        """POST /v1/sessions → SteelSession with the WS URL we construct.

        timeout_seconds caps the session at the vendor (Steel free tier
        also caps at 15 min). Setting it lower than the cap helps reap
        leaks if the proxy crashes without releasing."""
        body: dict = {
            "sessionTimeout": int(timeout_seconds) * 1000,  # Steel takes ms
            "solveCaptcha": bool(solve_captcha),
            "blockAds": True,
        }
        if profile_id:
            body["profileId"] = profile_id
        data = await self._request("POST", "/v1/sessions", json=body)
        sid = data.get("id")
        if not sid:
            raise SteelError(f"create_session: response missing id: {data!r}")
        ws = f"{STEEL_CDP_BASE}?apiKey={quote(self.api_key, safe='')}&sessionId={quote(sid, safe='')}"
        return SteelSession(
            session_id=sid,
            cdp_ws_url=ws,
            profile_id=profile_id,
            viewer_url=data.get("sessionViewerUrl"),
        )

    async def release_session(self, session_id: str) -> None:
        """POST /v1/sessions/{id}/release.

        Docs only confirm the SDK shape (client.sessions.release(id))
        so the REST verb/path here is the obvious mapping. If Steel
        ever changes this, the symptom is a 404/405 + a session that
        bills until its timeout. The proxy logs and continues — vendor
        timeout is the safety net."""
        try:
            await self._request(
                "POST", f"/v1/sessions/{quote(session_id, safe='')}/release"
            )
        except SteelError as e:
            if e.status in (404, 405):
                log.warning(
                    "steel release path returned %s — vendor will reap "
                    "at session timeout. SDK guidance suggests path is correct.",
                    e.status,
                )
            else:
                raise

    # ---- internals -------------------------------------------------------

    async def _request(
        self, method: str, path: str, *, json: Optional[dict] = None,
    ) -> dict:
        if not self.enabled or self._http is None:
            raise SteelError("steel adapter not started or STEEL_API_KEY unset")
        url = f"{STEEL_API_BASE}{path}"
        async with self._http.request(method, url, json=json) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise SteelError(
                    f"{method} {path} → {resp.status}", status=resp.status, body=body,
                )
            if not body:
                return {}
            try:
                import json as _json
                return _json.loads(body)
            except ValueError:
                return {"raw": body}
