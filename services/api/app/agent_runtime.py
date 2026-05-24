"""Per-department Hermes container lifecycle — Redis-backed for multi-worker scale.

One Docker container per (organization, department), exposing Hermes'
OpenAI-compatible API server on a per-dept port. Containers hibernate after
`hermes_idle_minutes` of inactivity and cold-start on the next chat request
(~10s).

State is stored in Redis so multiple API workers share a consistent view of
which containers are running. Distributed locks (Redlock-style via Redis
SET NX) prevent cold-start races across workers.

This module is intentionally Docker-only for now. When we deploy on Railway,
Modal, or Fly.io Machines, write a parallel runtime class and a small factory
in get_runtime().
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import redis.asyncio as redis
import yaml
from opentelemetry import trace as otel_trace

from app.config import get_settings
from app.telemetry import get_tracer, trace_container_lifecycle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


log = logging.getLogger(__name__)

IMAGE_TAG = "aki-hermes:0.13.0"
CONTAINER_INTERNAL_PORT = 8080

# Redis key prefixes
_REGISTRY_KEY = "hermes:registry"
_LOCK_PREFIX = "hermes:lock"
_LOCK_TTL_S = 30

ProcKey = tuple[UUID, UUID]


@dataclass
class HermesProcess:
    org_id: UUID
    department_id: UUID
    container_id: str
    host_port: int
    api_key: str
    started_at: float
    last_touched: float = field(default_factory=lambda: time.time())

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"

    def touch(self) -> None:
        self.last_touched = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": str(self.org_id),
            "department_id": str(self.department_id),
            "container_id": self.container_id,
            "host_port": self.host_port,
            "api_key": self.api_key,
            "started_at": self.started_at,
            "last_touched": self.last_touched,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HermesProcess:
        return cls(
            org_id=UUID(d["org_id"]),
            department_id=UUID(d["department_id"]),
            container_id=d["container_id"],
            host_port=d["host_port"],
            api_key=d["api_key"],
            started_at=d["started_at"],
            last_touched=d.get("last_touched", d["started_at"]),
        )


# In-memory cache for the local process — always checked before Redis
# to avoid network hops for the hot path.
_LOCAL_CACHE: dict[ProcKey, HermesProcess] = {}


async def _redis_pool() -> redis.Redis:
    """Lazy-init Redis connection pool."""
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


def _redis_key(org_id: UUID, dept_id: UUID) -> str:
    return f"{_REGISTRY_KEY}:{org_id}:{dept_id}"


def _lock_key(org_id: UUID, dept_id: UUID) -> str:
    return f"{_LOCK_PREFIX}:{org_id}:{dept_id}"


def _pick_free_port() -> int:
    """Bind ephemeral, close, return the port.

    In production with multiple workers on the same host, this is still
    race-prone. For true safety, use a port allocation service or bind
    the container to 0 and read the assigned port from Docker's port
    bindings. This is a pragmatic intermediate step.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _dept_dir(org_id: UUID, dept_id: UUID) -> Path:
    settings = get_settings()
    p = Path(settings.hermes_data_dir).expanduser() / str(org_id) / str(dept_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _container_name(org_id: UUID, dept_id: UUID) -> str:
    return f"aki-hermes-{str(org_id)[:8]}-{str(dept_id)[:8]}"


async def _acquire_lock(
    r: redis.Redis, org_id: UUID, dept_id: UUID, timeout_s: float = _LOCK_TTL_S
) -> bool:
    """Try to acquire a distributed lock for cold-starting this department.
    Returns True if lock was acquired."""
    key = _lock_key(org_id, dept_id)
    token = secrets.token_urlsafe(16)
    acquired = await r.set(key, token, nx=True, ex=int(timeout_s))
    return acquired is not None


async def _release_lock(r: redis.Redis, org_id: UUID, dept_id: UUID) -> None:
    await r.delete(_lock_key(org_id, dept_id))


async def _read_registry(r: redis.Redis, org_id: UUID, dept_id: UUID) -> HermesProcess | None:
    """Read process info from Redis registry."""
    raw = await r.get(_redis_key(org_id, dept_id))
    if raw is None:
        return None
    try:
        return HermesProcess.from_dict(json.loads(raw))
    except Exception:
        log.exception("corrupt registry entry for %s %s", org_id, dept_id)
        return None


async def _write_registry(r: redis.Redis, proc: HermesProcess) -> None:
    """Write process info to Redis registry."""
    await r.set(_redis_key(proc.org_id, proc.department_id), json.dumps(proc.to_dict()))


async def _delete_registry(r: redis.Redis, org_id: UUID, dept_id: UUID) -> None:
    await r.delete(_redis_key(org_id, dept_id))


async def _materialize_config(db: AsyncSession, org_id: UUID, dept_id: UUID) -> None:
    """Write the per-dept config.yaml under $HERMES_DATA_DIR/<org>/<dept>/."""
    from app.connectors.materialize import materialize_mcp_servers

    settings = get_settings()
    mcp_servers_list = await materialize_mcp_servers(db, org_id, dept_id)

    mcp_servers = {
        entry["name"]: {k: v for k, v in entry.items() if k != "name"} for entry in mcp_servers_list
    }

    config = {
        "model": {
            "provider": "custom",
            "default": settings.hermes_model_name,
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
        "mcp_servers": mcp_servers,
    }
    cfg_path = _dept_dir(org_id, dept_id) / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(config, sort_keys=False))


_tracer = get_tracer("aki.agent_runtime")


async def ensure_running(db: AsyncSession, org_id: UUID, dept_id: UUID) -> HermesProcess:
    """Idempotent: return a running per-(org,dept) Hermes process, cold-starting if needed.

    Uses a distributed Redis lock to prevent multiple workers from cold-starting
    the same department simultaneously.
    """
    with trace_container_lifecycle(
        _tracer, org_id=str(org_id), dept_id=str(dept_id), action="ensure_running"
    ) as span:
        key: ProcKey = (org_id, dept_id)

        # Fast path: local cache
        proc = _LOCAL_CACHE.get(key)
        if proc is not None and await _container_is_running_async(proc.container_id):
            proc.touch()
            span.set_attribute("cache.hit", True)
            # Best-effort async refresh of Redis timestamp
            asyncio.create_task(_touch_redis(key, proc))
            return proc

        r = await _redis_pool()

        # Second fast path: another worker may have started it
        proc = await _read_registry(r, org_id, dept_id)
        if proc is not None and await _container_is_running_async(proc.container_id):
            proc.touch()
            _LOCAL_CACHE[key] = proc
            span.set_attribute("cache.redis_hit", True)
            return proc

        # Slow path: we need to cold-start. Acquire distributed lock.
        lock_acquired = await _acquire_lock(r, org_id, dept_id)
        if not lock_acquired:
            # Another worker is cold-starting. Poll Redis until it appears.
            for _ in range(60):  # up to 30s
                await asyncio.sleep(0.5)
                proc = await _read_registry(r, org_id, dept_id)
                if proc is not None and await _container_is_running_async(proc.container_id):
                    proc.touch()
                    _LOCAL_CACHE[key] = proc
                    span.set_attribute("cache.lock_wait_hit", True)
                    return proc
            span.set_status(
                otel_trace.Status(otel_trace.StatusCode.ERROR, "cold-start lock timeout")
            )
            raise RuntimeError(
                f"timeout waiting for another worker to cold-start hermes for dept {dept_id}"
            )

        try:
            # Double-check after acquiring lock (another worker may have finished)
            proc = await _read_registry(r, org_id, dept_id)
            if proc is not None and await _container_is_running_async(proc.container_id):
                proc.touch()
                _LOCAL_CACHE[key] = proc
                return proc

            span.set_attribute("cold_start", True)
            await _materialize_config(db, org_id, dept_id)
            proc = await _boot_container(org_id, dept_id)
            await _write_registry(r, proc)
            _LOCAL_CACHE[key] = proc
            span.set_attribute("container.id", proc.container_id[:12])
            span.set_attribute("container.port", proc.host_port)
            return proc
        finally:
            await _release_lock(r, org_id, dept_id)


async def _touch_redis(key: ProcKey, proc: HermesProcess) -> None:
    """Update last_touched in Redis (fire-and-forget)."""
    try:
        r = await _redis_pool()
        proc.touch()
        await _write_registry(r, proc)
    except Exception:
        log.exception("failed to touch redis registry")


async def _container_is_running_async(container_id: str) -> bool:
    """Async wrapper for Docker container status check."""
    return await asyncio.to_thread(_container_is_running, container_id)


def _container_is_running(container_id: str) -> bool:
    import docker
    from docker.errors import NotFound

    client = docker.from_env()
    try:
        c = client.containers.get(container_id)
        return c.status == "running"
    except NotFound:
        return False


async def _boot_container(org_id: UUID, dept_id: UUID) -> HermesProcess:
    import docker

    settings = get_settings()
    client = docker.from_env()
    port = _pick_free_port()
    api_key = secrets.token_urlsafe(32)
    dept_dir = _dept_dir(org_id, dept_id)

    def _run() -> Any:
        return client.containers.run(
            image=IMAGE_TAG,
            name=_container_name(org_id, dept_id),
            detach=True,
            ports={f"{CONTAINER_INTERNAL_PORT}/tcp": port},
            volumes={str(dept_dir.resolve()): {"bind": "/opt/data", "mode": "rw"}},
            environment={
                "HERMES_HOME": "/opt/data",
                "HOME": "/opt/data",
                "OPENAI_API_KEY": settings.openai_api_key or "",
                "API_SERVER_HOST": "0.0.0.0",
                "API_SERVER_PORT": str(CONTAINER_INTERNAL_PORT),
                "API_SERVER_KEY": api_key,
            },
            entrypoint=["sh", "-c"],
            command=["hermes gateway run -v 2>&1"],
            auto_remove=False,
            restart_policy={"Name": "no"},
            # Resource limits for multi-tenant safety
            mem_limit="2g",
            cpu_quota=100000,  # 1 CPU core
            cpu_period=100000,
        )

    container = await asyncio.to_thread(_run)
    await _wait_for_api(port, api_key, timeout_s=30)

    return HermesProcess(
        org_id=org_id,
        department_id=dept_id,
        container_id=container.id,
        host_port=port,
        api_key=api_key,
        started_at=time.time(),
    )


async def _wait_for_api(port: int, api_key: str, *, timeout_s: float) -> None:
    """Poll /v1/models until 200 or timeout."""
    import httpx

    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=2.0) as c:
        while time.time() < deadline:
            try:
                r = await c.get(
                    f"http://127.0.0.1:{port}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if r.status_code == 200:
                    return
            except Exception as e:
                last_err = e
            await asyncio.sleep(0.5)
    raise RuntimeError(
        f"hermes container did not become ready on port {port} within {timeout_s}s: {last_err}"
    )


async def shutdown(key: ProcKey) -> None:
    """Stop and remove a single per-(org,dept) container."""
    _LOCAL_CACHE.pop(key, None)
    org_id, dept_id = key
    r = await _redis_pool()
    await _delete_registry(r, org_id, dept_id)

    import docker
    from docker.errors import NotFound

    client = docker.from_env()

    def _stop() -> None:
        try:
            c = client.containers.get(_container_name(org_id, dept_id))
            c.stop(timeout=10)
            c.remove(force=True)
        except NotFound:
            pass

    await asyncio.to_thread(_stop)


async def hibernate_idle(idle_minutes: int | None = None) -> int:
    """Stop containers idle longer than `idle_minutes`. Returns count stopped."""
    settings = get_settings()
    limit_s = (idle_minutes or settings.hermes_idle_minutes) * 60
    now = time.time()

    r = await _redis_pool()
    to_stop: list[ProcKey] = []

    # Scan all registered containers
    async for key in r.scan_iter(match=f"{_REGISTRY_KEY}:*"):
        raw = await r.get(key)
        if not raw:
            continue
        try:
            proc = HermesProcess.from_dict(json.loads(raw))
            if now - proc.last_touched > limit_s:
                to_stop.append((proc.org_id, proc.department_id))
        except Exception:
            log.exception("failed to parse registry entry %s", key)

    for key in to_stop:
        log.info("hibernating org=%s dept=%s", key[0], key[1])
        await shutdown(key)
    return len(to_stop)


async def hibernation_loop(interval_s: int = 60) -> None:
    """Background task. Cancel on shutdown."""
    while True:
        try:
            await hibernate_idle()
        except Exception:
            log.exception("hibernation tick failed")
        await asyncio.sleep(interval_s)


async def shutdown_all() -> None:
    """Stop every tracked container. Called from FastAPI lifespan exit."""
    r = await _redis_pool()
    keys: list[ProcKey] = []
    async for key in r.scan_iter(match=f"{_REGISTRY_KEY}:*"):
        raw = await r.get(key)
        if raw:
            try:
                proc = HermesProcess.from_dict(json.loads(raw))
                keys.append((proc.org_id, proc.department_id))
            except Exception:
                pass

    for key in keys:
        try:
            await shutdown(key)
        except Exception:
            log.exception("shutdown failed for key=%s", key)

    _LOCAL_CACHE.clear()


async def reap_orphans() -> int:
    """On startup, remove any `aki-hermes-*` containers that aren't in the
    Redis registry. Handles the case where uvicorn was killed without
    running its lifespan shutdown.
    """
    r = await _redis_pool()
    registered_names: set[str] = set()
    async for key in r.scan_iter(match=f"{_REGISTRY_KEY}:*"):
        raw = await r.get(key)
        if raw:
            try:
                proc = HermesProcess.from_dict(json.loads(raw))
                registered_names.add(_container_name(proc.org_id, proc.department_id))
            except Exception:
                pass

    import docker

    client = docker.from_env()

    def _list_and_kill() -> int:
        n = 0
        for c in client.containers.list(all=True, filters={"name": "aki-hermes-"}):
            if c.name not in registered_names:
                with contextlib.suppress(Exception):
                    c.stop(timeout=5)
                try:
                    c.remove(force=True)
                    n += 1
                except Exception:
                    pass
        return n

    return await asyncio.to_thread(_list_and_kill)
