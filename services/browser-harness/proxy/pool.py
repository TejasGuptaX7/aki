"""Per-(org, agent, platform) session pool — v2 edition.

The session "object" here is a remote CDP WebSocket, not a local
Chromium. Cold start = one REST call to a vendor + one WS connect
(~600–1500 ms typical). Reaping = closing the WS and letting the
vendor stop billing.

The pool also tracks the *current platform* per (org, agent) so that
tools without a URL argument (click, type, screenshot, …) route to
the last-navigated session.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from browserbase_adapter import BrowserbaseAdapter, BrowserbaseError
from cdp import CDPClient, attach_first_real_page
from profile_store import Manifest, ProfileStore
from router import BACKEND_BROWSERBASE, BACKEND_STEEL, Route
from steel_adapter import SteelAdapter, SteelError

log = logging.getLogger(__name__)

IDLE_SECONDS = int(os.environ.get("BROWSER_HARNESS_IDLE_SECONDS", "600"))
HARD_MAX_SECONDS = int(os.environ.get("BROWSER_HARNESS_HARD_MAX_SECONDS", "1800"))
REAPER_TICK_SECONDS = 30


class VendorError(Exception):
    """Wraps both SteelError and BrowserbaseError under a single type the
    server layer can catch. Carries the original .vendor and .status."""

    def __init__(self, vendor: str, message: str, status: Optional[int] = None):
        super().__init__(f"{vendor}: {message}")
        self.vendor = vendor
        self.status = status


@dataclass
class Session:
    org_id: str
    agent_id: str
    platform: str
    backend: str
    vendor_session_id: str
    cdp: CDPClient
    cdp_session_id: str           # attached page sessionId (flat mode)
    started_at: float
    idle_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False

    def deadline_reasons(self, now: float) -> list[str]:
        out = []
        if now - self.idle_at > IDLE_SECONDS:
            out.append(f"idle>{IDLE_SECONDS}s")
        if now - self.started_at > HARD_MAX_SECONDS:
            out.append(f"wallclock>{HARD_MAX_SECONDS}s")
        return out


class BrowserPoolV2:
    def __init__(
        self,
        store: ProfileStore,
        steel: SteelAdapter,
        browserbase: BrowserbaseAdapter,
    ):
        self.store = store
        self.steel = steel
        self.browserbase = browserbase
        self._sessions: dict[tuple[str, str, str], Session] = {}
        self._create_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        # (org, agent) → last-bound platform; tools w/o URL fall back to this.
        self._current_platform: dict[tuple[str, str], str] = {}
        self._reaper_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        await asyncio.gather(self.steel.start(), self.browserbase.start())
        self._reaper_task = asyncio.create_task(self._reaper(), name="pool-v2-reaper")
        log.info(
            "pool_v2_started idle=%ds hard=%ds steel=%s browserbase=%s",
            IDLE_SECONDS, HARD_MAX_SECONDS,
            self.steel.enabled, self.browserbase.enabled,
        )

    async def stop(self) -> None:
        self._stopping.set()
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
        keys = list(self._sessions.keys())
        await asyncio.gather(
            *(self._close_session(k, persist=True, reason="shutdown") for k in keys),
            return_exceptions=True,
        )
        await asyncio.gather(self.steel.stop(), self.browserbase.stop())

    # ---- platform binding -------------------------------------------------

    def current_platform(self, org_id: str, agent_id: str) -> Optional[str]:
        return self._current_platform.get((org_id, agent_id))

    def bind_platform(self, org_id: str, agent_id: str, platform: str) -> None:
        self._current_platform[(org_id, agent_id)] = platform

    def active_platforms(self, org_id: str, agent_id: str) -> list[Session]:
        return [
            s for (o, a, _), s in self._sessions.items()
            if o == org_id and a == agent_id and not s.closed
        ]

    # ---- acquire / release ------------------------------------------------

    @asynccontextmanager
    async def acquire(self, org_id: str, agent_id: str, route: Route):
        """Yield a Session for (org, agent, platform), creating one on
        miss. Updates current_platform on entry so subsequent
        toolless-URL calls land here."""
        key = (org_id, agent_id, route.platform)
        sess = await self._get_or_create(org_id, agent_id, route)
        await sess.lock.acquire()
        try:
            if sess.closed:
                # Reaper landed between get_or_create and lock.acquire —
                # drop and retry. The lock we hold is on a tombstone.
                sess.lock.release()
                async with self._key_lock(key):
                    if self._sessions.get(key) is sess:
                        await self._close_session(
                            key, persist=False, reason="dead_on_acquire"
                        )
                sess = await self._get_or_create(org_id, agent_id, route)
                await sess.lock.acquire()
            self.bind_platform(org_id, agent_id, route.platform)
            yield sess
        finally:
            sess.idle_at = time.monotonic()
            if sess.lock.locked():
                sess.lock.release()

    async def release_platform(
        self, org_id: str, agent_id: str, platform: str, *, persist: bool = True
    ) -> bool:
        key = (org_id, agent_id, platform)
        return await self._close_session(
            key, persist=persist, reason="explicit_release"
        )

    # ---- internals -------------------------------------------------------

    def _key_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        lk = self._create_locks.get(key)
        if lk is None:
            lk = self._create_locks[key] = asyncio.Lock()
        return lk

    async def _get_or_create(
        self, org_id: str, agent_id: str, route: Route
    ) -> Session:
        key = (org_id, agent_id, route.platform)
        sess = self._sessions.get(key)
        if sess and not sess.closed:
            return sess
        async with self._key_lock(key):
            sess = self._sessions.get(key)
            if sess and not sess.closed:
                return sess
            sess = await self._create_session(org_id, agent_id, route)
            self._sessions[key] = sess
            return sess

    async def _create_session(
        self, org_id: str, agent_id: str, route: Route,
    ) -> Session:
        # 1. Load or mint manifest.
        manifest = await self.store.get(org_id, agent_id, route.platform)
        if manifest and manifest.backend != route.backend:
            # Routing changed since the manifest was written. We honor
            # the new backend (router is the source of truth) and drop
            # the stale handle — the agent loses persisted state for
            # this platform, but that's the lesser evil vs continuing
            # to talk to the wrong vendor.
            log.warning(
                "manifest_backend_mismatch org=%s agent=%s platform=%s "
                "manifest=%s route=%s — minting new",
                org_id, agent_id, route.platform, manifest.backend, route.backend,
            )
            await self.store.delete(org_id, agent_id, route.platform)
            manifest = None

        if route.backend == BACKEND_STEEL:
            if not self.steel.enabled:
                raise VendorError("steel", "STEEL_API_KEY not configured")
            if manifest is None:
                try:
                    profile_id = await self.steel.create_profile()
                except SteelError as e:
                    raise VendorError("steel", str(e), e.status)
                manifest = Manifest(backend=BACKEND_STEEL, steel_profile_id=profile_id)
                await self.store.put(org_id, agent_id, route.platform, manifest)
            try:
                vendor_sess = await self.steel.create_session(
                    profile_id=manifest.steel_profile_id,
                )
            except SteelError as e:
                raise VendorError("steel", str(e), e.status)
            ws_url = vendor_sess.cdp_ws_url
            vendor_id = vendor_sess.session_id
        elif route.backend == BACKEND_BROWSERBASE:
            if not self.browserbase.enabled:
                raise VendorError(
                    "browserbase",
                    "BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID not configured",
                )
            if manifest is None:
                try:
                    ctx_id = await self.browserbase.create_context()
                except BrowserbaseError as e:
                    raise VendorError("browserbase", str(e), e.status)
                manifest = Manifest(
                    backend=BACKEND_BROWSERBASE, browserbase_context_id=ctx_id,
                )
                await self.store.put(org_id, agent_id, route.platform, manifest)
            try:
                vendor_sess = await self.browserbase.create_session(
                    context_id=manifest.browserbase_context_id, persist=True,
                )
            except BrowserbaseError as e:
                raise VendorError("browserbase", str(e), e.status)
            ws_url = vendor_sess.cdp_ws_url
            vendor_id = vendor_sess.session_id
        else:
            raise VendorError(route.backend, f"unknown backend {route.backend!r}")

        cdp = CDPClient(ws_url)
        try:
            await cdp.connect()
            cdp_sid = await attach_first_real_page(cdp)
        except Exception:
            await cdp.close()
            # Best-effort release of the vendor session — don't leak billable time.
            await self._release_vendor(route.backend, vendor_id)
            raise

        now = time.monotonic()
        sess = Session(
            org_id=org_id, agent_id=agent_id, platform=route.platform,
            backend=route.backend, vendor_session_id=vendor_id,
            cdp=cdp, cdp_session_id=cdp_sid,
            started_at=now, idle_at=now,
        )
        log.info(
            "session_v2_created org=%s agent=%s platform=%s backend=%s vendor_id=%s",
            org_id, agent_id, route.platform, route.backend, vendor_id,
        )
        return sess

    async def _close_session(
        self, key: tuple[str, str, str], *, persist: bool, reason: str,
    ) -> bool:
        sess = self._sessions.pop(key, None)
        if sess is None or sess.closed:
            return False
        sess.closed = True
        log.info(
            "session_v2_close org=%s agent=%s platform=%s reason=%s persist=%s",
            sess.org_id, sess.agent_id, sess.platform, reason, persist,
        )
        try:
            await sess.cdp.close()
        except Exception:
            log.warning("cdp_close_failed key=%s", key)
        try:
            await self._release_vendor(sess.backend, sess.vendor_session_id)
        except Exception:
            log.warning("vendor_release_failed key=%s", key)
        if not persist:
            # Drop the manifest + delete the vendor-side container.
            if sess.backend == BACKEND_STEEL:
                manifest = await self.store.get(
                    sess.org_id, sess.agent_id, sess.platform
                )
                if manifest and manifest.steel_profile_id:
                    try:
                        await self.steel.delete_profile(manifest.steel_profile_id)
                    except SteelError:
                        log.warning(
                            "steel_profile_delete_failed id=%s",
                            manifest.steel_profile_id,
                        )
            # Browserbase has no public DELETE for contexts as of writing;
            # data inside expires per plan retention. We just drop our
            # manifest; the context lingers on Browserbase until TTL.
            await self.store.delete(sess.org_id, sess.agent_id, sess.platform)
        # If this was the bound platform for the (org, agent), unbind it.
        cur = self._current_platform.get((sess.org_id, sess.agent_id))
        if cur == sess.platform:
            self._current_platform.pop((sess.org_id, sess.agent_id), None)
        return True

    async def _release_vendor(self, backend: str, vendor_session_id: str) -> None:
        if backend == BACKEND_STEEL:
            try:
                await self.steel.release_session(vendor_session_id)
            except SteelError as e:
                log.warning("steel release failed id=%s err=%s", vendor_session_id, e)
        elif backend == BACKEND_BROWSERBASE:
            try:
                await self.browserbase.release_session(vendor_session_id)
            except BrowserbaseError as e:
                log.warning("bb release failed id=%s err=%s", vendor_session_id, e)

    async def _reaper(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=REAPER_TICK_SECONDS
                )
                return
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            for key, sess in list(self._sessions.items()):
                if sess.lock.locked():
                    continue   # in use; refresh on release
                reasons = sess.deadline_reasons(now)
                if reasons:
                    await self._close_session(
                        key, persist=True, reason=",".join(reasons),
                    )
