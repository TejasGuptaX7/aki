"""Browserbase REST + Contexts adapter.

See PROTOCOL_v2.md §3 for the routing decision. This module owns
*only* the vendor wire shape — no MCP, no profile bookkeeping (that's
profile_store.py).

Browserbase docs reference:
  REST base:    https://api.browserbase.com
  Auth header:  X-BB-API-Key
  POST /v1/sessions     — body.browserSettings.context.{id,persist} attaches a Context
  POST /v1/contexts     — body.projectId; response {id, ...}
  Release:      POST /v1/sessions/{id}  body={"status": "REQUEST_RELEASE"}
  CDP WS:       response.connectUrl     (Browserbase gives us a fully-qualified wss URL)

Contexts encrypt customer state E2E (AES-256-CBC) so Browserbase
cannot decrypt cookies even with subpoena — relevant for our
compliance posture but invisible to the wire shape here.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

BB_API_BASE = os.environ.get("BROWSERBASE_API_BASE", "https://api.browserbase.com").rstrip("/")
BB_RELEASE_STATUS = "REQUEST_RELEASE"


class BrowserbaseError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class BrowserbaseSession:
    session_id: str
    cdp_ws_url: str          # `connectUrl` from create response
    context_id: Optional[str]
    selenium_url: Optional[str]


class BrowserbaseAdapter:
    """One adapter instance per server process."""

    def __init__(
        self, api_key: Optional[str] = None, project_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("BROWSERBASE_API_KEY")
        self.project_id = project_id or os.environ.get("BROWSERBASE_PROJECT_ID")
        self._http: Optional[aiohttp.ClientSession] = None

    @property
    def enabled(self) -> bool:
        # project_id is required by the API on session create; without it we
        # can't function. We don't require it on context create (the API
        # infers from key in some plans) but enforce it here for safety.
        return bool(self.api_key and self.project_id)

    async def start(self) -> None:
        if not self.api_key:
            log.warning(
                "browserbase_disabled — set BROWSERBASE_API_KEY (and "
                "BROWSERBASE_PROJECT_ID) to enable Browserbase routing"
            )
            return
        if not self.project_id:
            log.warning(
                "browserbase_partial — BROWSERBASE_API_KEY set but "
                "BROWSERBASE_PROJECT_ID missing; create_session will fail"
            )
        self._http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"X-BB-API-Key": self.api_key, "Content-Type": "application/json"},
        )
        log.info("browserbase_adapter_started base=%s", BB_API_BASE)

    async def stop(self) -> None:
        if self._http:
            await self._http.close()
            self._http = None

    # ---- contexts --------------------------------------------------------

    async def create_context(self) -> str:
        """POST /v1/contexts → context id. Optional projectId in body."""
        body = {"projectId": self.project_id} if self.project_id else {}
        data = await self._request("POST", "/v1/contexts", json=body)
        cid = data.get("id")
        if not cid:
            raise BrowserbaseError(
                f"create_context: response missing id: {data!r}"
            )
        return cid

    # ---- sessions --------------------------------------------------------

    async def create_session(
        self,
        *,
        context_id: Optional[str] = None,
        persist: bool = True,
        timeout_seconds: int = 3600,
        solve_captchas: bool = True,
    ) -> BrowserbaseSession:
        """POST /v1/sessions → BrowserbaseSession with vendor's connectUrl.

        When `context_id` is provided and `persist=True`, the session
        attaches to the context and writes cookie/localStorage/IDB
        changes back. With `persist=False`, the session can read from
        the context but updates are discarded — useful for read-only
        operations on a shared persona.
        """
        body: dict = {
            "projectId": self.project_id,
            "browserSettings": {
                "solveCaptchas": bool(solve_captchas),
            },
            "timeout": int(timeout_seconds),
        }
        if context_id:
            body["browserSettings"]["context"] = {
                "id": context_id, "persist": bool(persist),
            }
        data = await self._request("POST", "/v1/sessions", json=body)
        sid = data.get("id")
        connect_url = data.get("connectUrl")
        if not sid or not connect_url:
            raise BrowserbaseError(
                f"create_session: response missing id/connectUrl: {data!r}"
            )
        return BrowserbaseSession(
            session_id=sid,
            cdp_ws_url=connect_url,
            context_id=context_id,
            selenium_url=data.get("seleniumRemoteUrl"),
        )

    async def release_session(self, session_id: str) -> None:
        """POST /v1/sessions/{id} body={"status": "REQUEST_RELEASE"}.

        Browserbase doesn't expose DELETE — the only way to end a
        session is to set its status to REQUEST_RELEASE. Idempotent:
        re-requesting a release on an already-released session returns
        the session record with the COMPLETED status, which is fine."""
        body = {"status": BB_RELEASE_STATUS}
        if self.project_id:
            body["projectId"] = self.project_id
        try:
            await self._request(
                "POST", f"/v1/sessions/{quote(session_id, safe='')}", json=body,
            )
        except BrowserbaseError as e:
            if e.status in (404, 410):  # already gone — fine
                return
            raise

    # ---- internals -------------------------------------------------------

    async def _request(
        self, method: str, path: str, *, json: Optional[dict] = None,
    ) -> dict:
        if not self.api_key or self._http is None:
            raise BrowserbaseError("browserbase adapter not started or BROWSERBASE_API_KEY unset")
        url = f"{BB_API_BASE}{path}"
        async with self._http.request(method, url, json=json) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise BrowserbaseError(
                    f"{method} {path} → {resp.status}", status=resp.status, body=body,
                )
            if not body:
                return {}
            try:
                import json as _json
                return _json.loads(body)
            except ValueError:
                return {"raw": body}
