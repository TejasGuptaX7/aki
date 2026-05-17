"""Minimal async Chrome DevTools Protocol client over WebSocket.

Speaks CDP directly to whatever WS URL an adapter handed us. Replaces
the v1 browser-harness daemon + IPC layer — since the vendor *is*
remote Chrome, there's no daemon to multiplex through.

Wire shape (one line per object, newline-delimited not required):
  request:  {"id": 7, "method": "Page.navigate", "params": {"url": "..."}}
  reply:    {"id": 7, "result": {...}}            or
            {"id": 7, "error": {"code": -32601, "message": "..."}}
  event:    {"method": "Page.frameNavigated", "params": {...}}

Multi-session targets (Browserbase/Steel both surface multiple page
targets) carry `sessionId` on each frame; we attach via flat session
mode (Target.attachToTarget {flatten: true}) so all messages live on
the one root WS.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import aiohttp

log = logging.getLogger(__name__)


class CDPError(Exception):
    """Raised when the remote returns an `error` envelope or the WS dies
    mid-request."""

    def __init__(self, message: str, *, code: Optional[int] = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class CDPClient:
    """One open WS to one remote Chrome.

    Usage:
        async with CDPClient(ws_url) as cdp:
            await cdp.send("Page.enable", session_id=sid)
            result = await cdp.send("Page.navigate", {"url": "..."}, session_id=sid)
    """

    def __init__(self, ws_url: str, *, default_timeout: float = 30.0):
        self.ws_url = ws_url
        self.default_timeout = default_timeout
        self._http: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._events: list[dict] = []
        self._reader_task: Optional[asyncio.Task] = None
        self._closed = asyncio.Event()
        self._lock = asyncio.Lock()  # serialises socket writes

    async def __aenter__(self) -> "CDPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        # heartbeat=15: vendor proxies idle-close at 60s on some plans;
        # cheap ping keeps the WS alive across slow tool calls.
        self._http = aiohttp.ClientSession()
        self._ws = await self._http.ws_connect(
            self.ws_url,
            heartbeat=15,
            max_msg_size=64 * 1024 * 1024,  # screenshots can be >1 MiB base64
            timeout=20,
        )
        self._reader_task = asyncio.create_task(self._reader(), name="cdp-reader")

    async def close(self) -> None:
        self._closed.set()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._http is not None:
            await self._http.close()
        # Drain any in-flight callers with a clean error.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(CDPError("CDP WS closed"))
        self._pending.clear()

    async def send(
        self,
        method: str,
        params: Optional[dict] = None,
        *,
        session_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Send one CDP request, await its reply. Returns `result` dict
        on success, raises CDPError on `error` or timeout."""
        if self._ws is None or self._ws.closed:
            raise CDPError("CDP WS not connected")
        msg_id = self._next_id = self._next_id + 1
        msg: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id is not None:
            msg["sessionId"] = session_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[msg_id] = fut
        try:
            async with self._lock:
                await self._ws.send_str(json.dumps(msg))
            try:
                resp = await asyncio.wait_for(fut, timeout or self.default_timeout)
            except asyncio.TimeoutError:
                raise CDPError(f"CDP {method} timed out after {timeout or self.default_timeout}s")
        finally:
            self._pending.pop(msg_id, None)
        if "error" in resp:
            err = resp["error"]
            raise CDPError(
                err.get("message", "CDP error"),
                code=err.get("code"),
                data=err.get("data"),
            )
        return resp.get("result", {}) or {}

    def drain_events(self) -> list[dict]:
        """Return + clear the buffered events. Useful for wait_for_network_idle
        and any caller that listens for CDP notifications."""
        out, self._events = self._events, []
        return out

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        obj = json.loads(msg.data)
                    except json.JSONDecodeError:
                        log.warning("cdp_bad_frame: %.200s", msg.data)
                        continue
                    mid = obj.get("id")
                    if mid is not None:
                        fut = self._pending.get(mid)
                        if fut and not fut.done():
                            fut.set_result(obj)
                        else:
                            log.debug("cdp_orphan_reply id=%s", mid)
                    else:
                        # event
                        self._events.append(obj)
                        # Cap the buffer at 1000 events to bound memory if
                        # a long-running tool never drains.
                        if len(self._events) > 1000:
                            self._events = self._events[-500:]
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.warning("cdp_ws_error: %s", self._ws.exception())
                    break
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception:
            log.exception("cdp_reader_crashed")
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CDPError("CDP WS reader exited"))


async def attach_first_real_page(cdp: CDPClient) -> str:
    """Attach the WS to a real page target and return its sessionId.

    Both vendors hand us a WS to the *browser* target; we still need
    to attach to a page (flat session mode) before Page/Runtime/DOM
    calls work."""
    targets = (await cdp.send("Target.getTargets")).get("targetInfos", [])
    pages = [
        t for t in targets
        if t.get("type") == "page" and not _is_internal(t.get("url", ""))
    ]
    if not pages:
        tid = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
    else:
        tid = pages[0]["targetId"]
    sid = (
        await cdp.send(
            "Target.attachToTarget", {"targetId": tid, "flatten": True}
        )
    )["sessionId"]
    # Enable the domains a typical tool call depends on; do in parallel.
    await asyncio.gather(
        cdp.send("Page.enable", session_id=sid),
        cdp.send("Runtime.enable", session_id=sid),
        cdp.send("DOM.enable", session_id=sid),
        cdp.send("Network.enable", session_id=sid),
        return_exceptions=True,
    )
    return sid


def _is_internal(url: str) -> bool:
    return url.startswith(
        ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")
    )
