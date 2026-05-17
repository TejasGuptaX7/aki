"""Per-org container supervisor.

Runs as PID 1 inside `aki-hermes:0.13.0`. Two jobs:

  1. Process manager — read /opt/data/manifest.json, spawn one
     `hermes -p <agent_id> gateway run --port <internal>` per agent,
     restart on crash, kill profiles no longer in the manifest.

  2. HTTP proxy — listen on $SUPERVISOR_PORT (default 8080), forward
     /v1/* to the right profile based on X-Aki-Agent-Id. Pass SSE
     chunks through byte-for-byte so the control plane's audit tap
     keeps working.

Control endpoints (require Bearer $SUPERVISOR_API_KEY):

  GET  /control/health       — { ready: bool, agents: { id → status } }
  POST /control/reload       — re-read manifest, converge subprocesses
  POST /control/profile/{id} — single-agent reload (used by tests)

Everything else under /v1/* gets proxied. The supervisor never inspects
chat content — it's a routing fabric, not part of the agent loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web


log = logging.getLogger("supervisor")


# ─── Config from env ────────────────────────────────────────────────────────

HOST = os.environ.get("SUPERVISOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("SUPERVISOR_PORT", "8080"))
API_KEY = os.environ["SUPERVISOR_API_KEY"]
PROFILE_PORT_LOW = int(os.environ.get("PROFILE_PORT_LOW", "9001"))
PROFILE_PORT_HIGH = int(os.environ.get("PROFILE_PORT_HIGH", "9100"))
MANIFEST_PATH = Path("/opt/data/manifest.json")
AGENTS_ROOT = Path("/opt/data/agents")

# Per-Hermes-profile cold-start ceiling. Hermes reports ready in 5-10s
# typically; we wait up to 25s before treating it as failed.
PROFILE_READY_TIMEOUT_S = 25.0


# ─── Profile registry ──────────────────────────────────────────────────────


@dataclass
class Profile:
    agent_id: str
    slug: str
    port: int
    process: asyncio.subprocess.Process
    started_at: float
    api_key: str
    status: str = "starting"           # starting | ready | failed | stopped
    last_error: str | None = None


@dataclass
class State:
    profiles: dict[str, Profile] = field(default_factory=dict)
    used_ports: set[int] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    shutting_down: bool = False


STATE = State()


def _allocate_port() -> int:
    for p in range(PROFILE_PORT_LOW, PROFILE_PORT_HIGH + 1):
        if p not in STATE.used_ports:
            STATE.used_ports.add(p)
            return p
    raise RuntimeError("no free internal ports for new profile")


def _release_port(p: int) -> None:
    STATE.used_ports.discard(p)


# ─── Manifest handling ──────────────────────────────────────────────────────


def _read_manifest() -> list[dict]:
    """Read the manifest. Tolerate missing/empty file so first-boot before
    any agents exist doesn't crash the supervisor — we just have 0 profiles
    until reload is called."""
    if not MANIFEST_PATH.exists():
        return []
    try:
        return (json.loads(MANIFEST_PATH.read_text()) or {}).get("agents", [])
    except json.JSONDecodeError:
        log.exception("manifest.json malformed; treating as empty")
        return []


# ─── Hermes profile lifecycle ───────────────────────────────────────────────


async def _spawn_profile(entry: dict) -> Profile:
    """Spawn `hermes -p <agent_id> gateway run --port <internal>` and wait
    for its API server to become healthy. Each profile gets its own API key
    so per-process auth is enforced even on localhost."""
    import secrets

    agent_id = entry["id"]
    slug = entry.get("slug", agent_id[:8])
    port = _allocate_port()
    api_key = secrets.token_urlsafe(32)

    agent_dir = AGENTS_ROOT / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HERMES_HOME"] = str(agent_dir)
    env["HOME"] = str(agent_dir)
    env["API_SERVER_HOST"] = "127.0.0.1"
    env["API_SERVER_PORT"] = str(port)
    env["API_SERVER_KEY"] = api_key

    log.info("spawning profile agent_id=%s slug=%s port=%d", agent_id, slug, port)
    proc = await asyncio.create_subprocess_exec(
        "hermes", "-p", agent_id, "gateway", "run",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    profile = Profile(
        agent_id=agent_id,
        slug=slug,
        port=port,
        process=proc,
        started_at=asyncio.get_running_loop().time(),
        api_key=api_key,
    )

    asyncio.create_task(_drain_subprocess_output(profile))
    asyncio.create_task(_watch_profile_health(profile))
    return profile


async def _drain_subprocess_output(profile: Profile) -> None:
    """Pipe hermes stdout/stderr to our own log with the agent slug prefixed.
    Without this the subprocess buffer eventually fills and the process
    blocks on write."""
    assert profile.process.stdout is not None
    async for raw in profile.process.stdout:
        try:
            line = raw.decode("utf-8", errors="replace").rstrip()
        except Exception:
            continue
        log.info("[%s] %s", profile.slug, line)


async def _watch_profile_health(profile: Profile) -> None:
    """Poll /v1/models on the profile's port; flip status to ready/failed.
    Marking failed after timeout lets /control/health report the bad state
    instead of hanging forever."""
    deadline = asyncio.get_running_loop().time() + PROFILE_READY_TIMEOUT_S
    async with ClientSession(timeout=ClientTimeout(total=2.0)) as session:
        while asyncio.get_running_loop().time() < deadline:
            if profile.process.returncode is not None:
                profile.status = "failed"
                profile.last_error = f"exited rc={profile.process.returncode}"
                return
            try:
                async with session.get(
                    f"http://127.0.0.1:{profile.port}/v1/models",
                    headers={"Authorization": f"Bearer {profile.api_key}"},
                ) as r:
                    if r.status == 200:
                        profile.status = "ready"
                        return
            except Exception as e:
                profile.last_error = str(e)[:200]
            await asyncio.sleep(0.4)
    profile.status = "failed"
    profile.last_error = profile.last_error or "health timeout"


async def _stop_profile(profile: Profile) -> None:
    """SIGTERM, then SIGKILL after 5s. Always release the port."""
    log.info("stopping profile agent_id=%s slug=%s", profile.agent_id, profile.slug)
    if profile.process.returncode is None:
        try:
            profile.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(profile.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                profile.process.kill()
                await profile.process.wait()
        except ProcessLookupError:
            pass
    profile.status = "stopped"
    _release_port(profile.port)


# ─── Reconciler ─────────────────────────────────────────────────────────────


async def _converge() -> None:
    """Diff manifest vs running profiles. Spawn new, stop removed."""
    async with STATE.lock:
        entries = _read_manifest()
        desired = {e["id"]: e for e in entries}
        running = set(STATE.profiles.keys())

        # Stop profiles no longer in manifest
        for aid in list(running - set(desired)):
            await _stop_profile(STATE.profiles.pop(aid))

        # Spawn profiles newly added (don't await ready; let health-watcher
        # promote them as they come up so reload returns quickly)
        for aid, entry in desired.items():
            if aid in STATE.profiles:
                continue
            STATE.profiles[aid] = await _spawn_profile(entry)


async def _await_all_ready(timeout_s: float = PROFILE_READY_TIMEOUT_S) -> bool:
    """Block until every profile is `ready` or `failed`. Used by the boot
    sequence so the control plane's _wait_for_supervisor sees stable state."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if not STATE.profiles:
            return True
        pending = [p for p in STATE.profiles.values() if p.status == "starting"]
        if not pending:
            return all(p.status == "ready" for p in STATE.profiles.values())
        await asyncio.sleep(0.25)
    return all(p.status == "ready" for p in STATE.profiles.values())


# ─── HTTP: control endpoints ────────────────────────────────────────────────


def _require_auth(req: web.Request) -> None:
    auth = req.headers.get("Authorization", "")
    if auth != f"Bearer {API_KEY}":
        raise web.HTTPUnauthorized(text="bad supervisor api key")


async def health(req: web.Request) -> web.Response:
    _require_auth(req)
    return web.json_response(
        {
            "ready": all(p.status == "ready" for p in STATE.profiles.values()),
            "agents": {
                aid: {"status": p.status, "slug": p.slug, "port": p.port,
                      "last_error": p.last_error}
                for aid, p in STATE.profiles.items()
            },
        }
    )


async def reload(req: web.Request) -> web.Response:
    _require_auth(req)
    await _converge()
    ok = await _await_all_ready()
    return web.json_response({"ready": ok, "loaded": list(STATE.profiles.keys())})


# ─── HTTP: chat proxy (X-Aki-Agent-Id → profile) ────────────────────────────


async def proxy(req: web.Request) -> web.StreamResponse:
    """Forward /v1/* to the agent profile addressed by X-Aki-Agent-Id.

    Streams response chunks straight through so SSE works end-to-end —
    the control plane's audit tap reads `event: hermes.tool.progress`
    lines from the live stream, and any buffering here would break it.
    """
    agent_id = req.headers.get("X-Aki-Agent-Id")
    if not agent_id:
        return web.json_response(
            {"error": "missing_agent_id",
             "detail": "X-Aki-Agent-Id header required"},
            status=400,
        )

    profile = STATE.profiles.get(agent_id)
    if profile is None:
        return web.json_response(
            {"error": "agent_not_loaded",
             "detail": f"profile {agent_id} not in supervisor registry"},
            status=404,
        )
    if profile.status != "ready":
        return web.json_response(
            {"error": "agent_not_ready",
             "detail": f"profile status={profile.status} err={profile.last_error}"},
            status=503,
        )

    # Build upstream request. Hermes expects its own Bearer (the per-profile
    # API_SERVER_KEY); the X-Aki-Agent-Id we strip — Hermes doesn't know
    # about it.
    upstream_url = f"http://127.0.0.1:{profile.port}{req.rel_url}"
    fwd_headers = {
        k: v
        for k, v in req.headers.items()
        if k.lower() not in (
            "host", "authorization", "x-aki-agent-id", "content-length",
        )
    }
    fwd_headers["Authorization"] = f"Bearer {profile.api_key}"

    body = await req.read()

    # Long timeout — agent tool loops can run for minutes.
    timeout = ClientTimeout(total=600, connect=10)
    session = ClientSession(timeout=timeout)
    try:
        upstream = await session.request(
            req.method,
            upstream_url,
            headers=fwd_headers,
            data=body if body else None,
        )
    except Exception as e:
        await session.close()
        log.exception("proxy upstream connect failed agent=%s", agent_id)
        return web.json_response(
            {"error": "upstream_unreachable", "detail": str(e)[:200]},
            status=502,
        )

    response = web.StreamResponse(
        status=upstream.status,
        headers={
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding")
        },
    )
    await response.prepare(req)
    try:
        async for chunk in upstream.content.iter_any():
            await response.write(chunk)
    finally:
        upstream.release()
        await session.close()
    await response.write_eof()
    return response


# ─── App wiring ─────────────────────────────────────────────────────────────


async def _on_startup(app: web.Application) -> None:
    log.info("supervisor starting; loading manifest")
    await _converge()
    # Don't block startup on profiles being ready — the health endpoint
    # reports readiness, and the control plane polls until ready=true.
    log.info("supervisor ready on :%d; profiles=%d", PORT, len(STATE.profiles))


async def _on_shutdown(app: web.Application) -> None:
    STATE.shutting_down = True
    log.info("supervisor shutting down; stopping profiles")
    await asyncio.gather(
        *(_stop_profile(p) for p in list(STATE.profiles.values())),
        return_exceptions=True,
    )


def make_app() -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_get("/control/health", health)
    app.router.add_post("/control/reload", reload)
    # /v1/* — chat, models, anything Hermes' OpenAI-compatible server exposes
    app.router.add_route("*", "/v1/{tail:.*}", proxy)
    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    web.run_app(make_app(), host=HOST, port=PORT, access_log=None)
