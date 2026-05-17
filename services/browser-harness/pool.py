"""Per-(org, agent) Chromium + browser-harness daemon pool.

Each session is:
  - one headless Chromium subprocess bound to a per-agent --user-data-dir
  - one browser-harness daemon subprocess (python -m browser_harness.daemon)
    keyed by BU_NAME so its IPC socket is isolated from other agents

A request acquires a session via `pool.acquire(org, agent)`. The first call for
a fresh tuple cold-starts both subprocesses (~2-4s typical). Subsequent calls
within idle_seconds reuse the existing pair. The reaper task hard-kills any
session past its idle or wall-clock deadline.

Concurrency model: a single asyncio.Lock per (org, agent) tuple. The MCP
server is single-process and single-threaded inside asyncio, so a per-session
lock is enough to prevent concurrent CDP calls from racing on the same Chrome.
This also serializes profile download/upload during create/release.

Horizontal scaling: the pool's state is in-memory. Front this with a sticky
LB keyed on (org_id, agent_id) — see PROTOCOL.md §5.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from storage import ProfileStorage

log = logging.getLogger(__name__)

CHROMIUM_BIN = os.environ.get("BROWSER_HARNESS_CHROMIUM", "/usr/bin/chromium")
PROFILE_ROOT = Path(
    os.environ.get(
        "BROWSER_HARNESS_PROFILE_ROOT", "/var/lib/aki/browser-profiles"
    )
).expanduser()
PORT_RANGE = (
    int(os.environ.get("BROWSER_HARNESS_PORT_MIN", "9300")),
    int(os.environ.get("BROWSER_HARNESS_PORT_MAX", "9999")),
)
IDLE_SECONDS = int(os.environ.get("BROWSER_HARNESS_IDLE_SECONDS", "600"))  # 10 min
HARD_MAX_SECONDS = int(os.environ.get("BROWSER_HARNESS_HARD_MAX_SECONDS", "1800"))  # 30 min
REAPER_TICK_SECONDS = 30
COLD_START_TIMEOUT = 30.0


@dataclass
class Session:
    org_id: str
    agent_id: str
    bu_name: str                          # daemon IPC namespace
    profile_dir: Path                     # Chromium --user-data-dir
    runtime_dir: Path                     # BH_RUNTIME_DIR (daemon sock/pid)
    tmp_dir: Path                         # BH_TMP_DIR (daemon log + screenshots)
    cdp_port: int                         # Chromium remote-debugging port
    chrome_proc: asyncio.subprocess.Process
    daemon_proc: asyncio.subprocess.Process
    started_at: float
    idle_at: float                        # last release time (monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False

    def deadline_reasons(self, now: float) -> list[str]:
        out = []
        if now - self.idle_at > IDLE_SECONDS:
            out.append(f"idle>{IDLE_SECONDS}s")
        if now - self.started_at > HARD_MAX_SECONDS:
            out.append(f"wallclock>{HARD_MAX_SECONDS}s")
        if self.chrome_proc.returncode is not None:
            out.append(f"chrome_exited({self.chrome_proc.returncode})")
        if self.daemon_proc.returncode is not None:
            out.append(f"daemon_exited({self.daemon_proc.returncode})")
        return out

    @property
    def ttl_seconds(self) -> int:
        return max(0, HARD_MAX_SECONDS - int(time.monotonic() - self.started_at))


class BrowserPool:
    def __init__(self, storage: ProfileStorage):
        self.storage = storage
        self._sessions: dict[tuple[str, str], Session] = {}
        self._create_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._used_ports: set[int] = set()
        self._reaper_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        await self.storage.ensure_bucket()
        self._reaper_task = asyncio.create_task(self._reaper(), name="pool-reaper")
        log.info(
            "pool_started profile_root=%s idle=%ds hard=%ds",
            PROFILE_ROOT, IDLE_SECONDS, HARD_MAX_SECONDS,
        )

    async def stop(self) -> None:
        self._stopping.set()
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
        # Close every active session, persisting profiles
        keys = list(self._sessions.keys())
        await asyncio.gather(
            *(self._close_session(k, persist=True, reason="shutdown") for k in keys),
            return_exceptions=True,
        )

    @asynccontextmanager
    async def acquire(self, org_id: str, agent_id: str):
        """Yield a Session for (org, agent), creating one on miss.

        The yielded session's lock is held for the duration of the
        `with` block — other concurrent requests for the same (org, agent)
        will queue behind it. Release-on-exit updates idle_at.
        """
        key = (org_id, agent_id)
        sess = await self._get_or_create(org_id, agent_id)
        await sess.lock.acquire()
        try:
            # Re-check after acquiring lock: another coroutine may have closed
            # the session between get_or_create and lock.acquire (e.g. reaper
            # ran on a stale idle_at). Recreate transparently.
            if sess.closed or _proc_dead(sess.chrome_proc) or _proc_dead(sess.daemon_proc):
                log.info(
                    "session_dead_on_acquire org=%s agent=%s reasons=%s",
                    org_id, agent_id, sess.deadline_reasons(time.monotonic()),
                )
                sess.lock.release()
                # Drop the dead entry and retry — the lock we just released
                # was on a tombstone; the new session gets a fresh lock.
                async with self._key_lock(key):
                    if self._sessions.get(key) is sess:
                        await self._close_session(key, persist=False, reason="dead_on_acquire")
                sess = await self._get_or_create(org_id, agent_id)
                await sess.lock.acquire()
            yield sess
        finally:
            sess.idle_at = time.monotonic()
            if sess.lock.locked():
                sess.lock.release()

    async def release(self, org_id: str, agent_id: str, persist: bool = True) -> bool:
        """Explicitly drop an agent's session. Used by the `release_session` tool."""
        return await self._close_session(
            (org_id, agent_id), persist=persist, reason="explicit_release"
        )

    def session(self, org_id: str, agent_id: str) -> Optional[Session]:
        return self._sessions.get((org_id, agent_id))

    # ---- internals -------------------------------------------------------

    def _key_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        lk = self._create_locks.get(key)
        if lk is None:
            lk = self._create_locks[key] = asyncio.Lock()
        return lk

    async def _get_or_create(self, org_id: str, agent_id: str) -> Session:
        key = (org_id, agent_id)
        sess = self._sessions.get(key)
        if sess and not sess.closed and not _proc_dead(sess.chrome_proc):
            return sess
        async with self._key_lock(key):
            sess = self._sessions.get(key)
            if sess and not sess.closed and not _proc_dead(sess.chrome_proc):
                return sess
            sess = await self._create_session(org_id, agent_id)
            self._sessions[key] = sess
            return sess

    async def _create_session(self, org_id: str, agent_id: str) -> Session:
        bu_name = _bu_name(org_id, agent_id)
        agent_root = PROFILE_ROOT / org_id / agent_id
        profile_dir = agent_root / "chrome-profile"
        runtime_dir = agent_root / "runtime"
        tmp_dir = agent_root / "tmp"
        for d in (profile_dir, runtime_dir, tmp_dir):
            d.mkdir(parents=True, exist_ok=True)

        restored = await self.storage.download(org_id, agent_id, profile_dir)
        log.info(
            "session_create_begin org=%s agent=%s profile_restored=%s",
            org_id, agent_id, restored,
        )

        port = self._alloc_port()
        chrome_proc = await _spawn_chromium(profile_dir, port)
        try:
            await _wait_for_devtools(port)
        except Exception:
            chrome_proc.terminate()
            self._used_ports.discard(port)
            raise

        daemon_proc = await _spawn_daemon(
            bu_name=bu_name, cdp_port=port, runtime_dir=runtime_dir, tmp_dir=tmp_dir
        )
        try:
            await _wait_for_daemon(bu_name, runtime_dir)
        except Exception:
            daemon_proc.terminate()
            chrome_proc.terminate()
            self._used_ports.discard(port)
            raise

        now = time.monotonic()
        sess = Session(
            org_id=org_id, agent_id=agent_id, bu_name=bu_name,
            profile_dir=profile_dir, runtime_dir=runtime_dir, tmp_dir=tmp_dir,
            cdp_port=port, chrome_proc=chrome_proc, daemon_proc=daemon_proc,
            started_at=now, idle_at=now,
        )
        log.info(
            "session_create_done org=%s agent=%s bu_name=%s cdp_port=%d chrome_pid=%d daemon_pid=%d",
            org_id, agent_id, bu_name, port, chrome_proc.pid, daemon_proc.pid,
        )
        return sess

    async def _close_session(
        self, key: tuple[str, str], *, persist: bool, reason: str
    ) -> bool:
        sess = self._sessions.pop(key, None)
        if sess is None:
            return False
        if sess.closed:
            return False
        sess.closed = True
        log.info(
            "session_close_begin org=%s agent=%s reason=%s persist=%s",
            sess.org_id, sess.agent_id, reason, persist,
        )
        # Kill daemon first — it owns the CDP socket and will dump errors if
        # Chrome dies under it. Then Chrome.
        for proc, label in ((sess.daemon_proc, "daemon"), (sess.chrome_proc, "chrome")):
            await _terminate_proc(proc, label, sess.bu_name)
        self._used_ports.discard(sess.cdp_port)
        if persist:
            try:
                await self.storage.upload(sess.org_id, sess.agent_id, sess.profile_dir)
            except Exception as e:
                log.exception(
                    "profile_persist_failed org=%s agent=%s err=%s",
                    sess.org_id, sess.agent_id, e,
                )
        # Best-effort cleanup of the runtime dir's daemon sock; the data
        # under profile_dir stays so a subsequent local-only run resumes.
        for f in ("bu.sock", "bu.pid", "bu.port"):
            try:
                (sess.runtime_dir / f).unlink()
            except FileNotFoundError:
                pass
        return True

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
                reasons = sess.deadline_reasons(now)
                if not reasons:
                    continue
                # If a request is currently holding the session lock, skip
                # this tick — the request will refresh idle_at on release.
                # Hard wallclock is honored on the *next* tick after release.
                if sess.lock.locked():
                    continue
                await self._close_session(key, persist=True, reason=",".join(reasons))

    def _alloc_port(self) -> int:
        for port in range(PORT_RANGE[0], PORT_RANGE[1] + 1):
            if port in self._used_ports:
                continue
            # Bind-probe — defends against external services on the port
            # (other tenants on the same box, k8s host-port collisions).
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", port))
            except OSError:
                continue
            self._used_ports.add(port)
            return port
        raise RuntimeError(
            f"no free CDP port in [{PORT_RANGE[0]},{PORT_RANGE[1]}]"
        )


def _bu_name(org_id: str, agent_id: str) -> str:
    """BU_NAME must match [A-Za-z0-9_-]{1,64}. Two raw UUIDs are 73 chars
    once concatenated — over budget. blake2b-64 of each gives 16 hex chars,
    so org+agent fits in 33 chars with room to spare for the 'a-' prefix
    (helps grep/tail the bu-*.sock files on the shared runtime dir)."""
    o = hashlib.blake2b(org_id.encode(), digest_size=8).hexdigest()
    a = hashlib.blake2b(agent_id.encode(), digest_size=8).hexdigest()
    return f"a-{o}-{a}"


def _proc_dead(p: asyncio.subprocess.Process) -> bool:
    return p.returncode is not None


async def _spawn_chromium(profile_dir: Path, port: int) -> asyncio.subprocess.Process:
    """Headless Chromium with remote debugging on `port`. Per-agent isolation
    is via `--user-data-dir`; --headless=new gives us a real renderer (the
    old --headless mode lacks Service Worker support, which breaks many
    modern auth flows)."""
    args = [
        CHROMIUM_BIN,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-address=127.0.0.1",
        "--headless=new",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--disable-dev-shm-usage",   # /dev/shm is small in containers → use /tmp
        "--disable-gpu",
        "--disable-software-rasterizer",
        # In a container, the default Chromium sandbox needs CAP_SYS_ADMIN;
        # we run unprivileged so disable. The container is the sandbox.
        "--no-sandbox",
        # Don't ever try to phone home / autoupdate.
        "--disable-component-update",
        "--disable-background-networking",
        "--metrics-recording-only",
        "--disable-breakpad",
        "--disable-features=Translate,OptimizationHints,InterestFeedContentSuggestions",
        # Resource constraints — these are *Chromium* flags; the actual
        # cgroups limits are enforced by the container runtime.
        "--js-flags=--max-old-space-size=512",
        # No window — but we do want an off-screen viewport size.
        "--window-size=1280,800",
        "about:blank",
    ]
    log.debug("spawn_chromium %s", " ".join(args[:6]))
    return await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
        # New session so SIGINT to the parent process group doesn't propagate
        # to Chromium; we explicitly terminate it on close.
        preexec_fn=os.setsid if sys.platform != "win32" else None,
    )


async def _wait_for_devtools(port: int, timeout: float = COLD_START_TIMEOUT) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    def _probe() -> bool:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1
            ).read()
            return True
        except (urllib.error.URLError, OSError):
            return False

    while loop.time() < deadline:
        if await loop.run_in_executor(None, _probe):
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(f"chromium devtools never came up on :{port} within {timeout}s")


async def _spawn_daemon(
    *, bu_name: str, cdp_port: int, runtime_dir: Path, tmp_dir: Path
) -> asyncio.subprocess.Process:
    """python -m browser_harness.daemon with BU_* env scoped to this agent."""
    env = {
        **os.environ,
        "BU_NAME": bu_name,
        "BU_CDP_URL": f"http://127.0.0.1:{cdp_port}",
        # BH_RUNTIME_DIR isolates the daemon's IPC sock/pid in a per-agent
        # directory — keeps the on-disk filenames as plain "bu.sock"/"bu.pid"
        # so co-tenants on the same host can't collide.
        "BH_RUNTIME_DIR": str(runtime_dir),
        "BH_TMP_DIR": str(tmp_dir),
        # Defensive: stop the daemon from autospawning a Browser Use cloud
        # browser if the API key happens to be in our env for some unrelated
        # reason (e.g. for the http_get proxy path).
        "BU_AUTOSPAWN": "",
    }
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "browser_harness.daemon",
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
        preexec_fn=os.setsid if sys.platform != "win32" else None,
    )


async def _wait_for_daemon(
    bu_name: str, runtime_dir: Path, timeout: float = COLD_START_TIMEOUT
) -> None:
    """Poll the daemon's BH_RUNTIME_DIR for the bu.sock + ping it.

    With BH_RUNTIME_DIR set, browser_harness._ipc names its socket plainly
    `bu.sock` (no BU_NAME suffix) — that's how the daemon and helpers find
    each other when running co-tenant on a shared box."""
    sock = runtime_dir / "bu.sock"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    def _ping() -> bool:
        # ipc.ping reads BH_RUNTIME_DIR from os.environ at import time, but
        # we don't actually use it — we connect manually with the right path.
        if not sock.exists():
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(str(sock))
            try:
                s.sendall((json.dumps({"meta": "ping"}) + "\n").encode())
                data = b""
                while not data.endswith(b"\n"):
                    chunk = s.recv(1 << 14)
                    if not chunk:
                        break
                    data += chunk
                resp = json.loads(data or b"{}")
                return isinstance(resp, dict) and resp.get("pong") is True
            finally:
                s.close()
        except (OSError, ValueError):
            return False

    while loop.time() < deadline:
        if await loop.run_in_executor(None, _ping):
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(
        f"browser_harness daemon (bu_name={bu_name}) never came up within {timeout}s"
    )


async def _terminate_proc(
    p: asyncio.subprocess.Process, label: str, bu_name: str
) -> None:
    if p.returncode is not None:
        return
    try:
        # SIGTERM first; give 3s to drain. Chrome's clean-shutdown writes
        # the SingletonLock file we need cleared for the next session.
        if sys.platform != "win32":
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        else:
            p.terminate()
        try:
            await asyncio.wait_for(p.wait(), timeout=3.0)
            return
        except asyncio.TimeoutError:
            pass
        if sys.platform != "win32":
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        else:
            p.kill()
        await p.wait()
    except (ProcessLookupError, PermissionError):
        pass
    except Exception as e:
        log.warning("terminate_failed label=%s bu=%s err=%s", label, bu_name, e)


# Re-export so server.py can introspect without hard-coding the constants.
__all__ = [
    "BrowserPool",
    "Session",
    "PROFILE_ROOT",
    "IDLE_SECONDS",
    "HARD_MAX_SECONDS",
]
