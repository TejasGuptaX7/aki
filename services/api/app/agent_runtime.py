"""Per-org Hermes container lifecycle.

One Docker container per organization, exposing Hermes' OpenAI-compatible
API server on a per-org port. Containers hibernate after `hermes_idle_minutes`
of inactivity and cold-start on the next chat request (~10s).

State (org_id → process handle) is in-memory in this process. For multi-worker
production deploys, swap _REGISTRY for a Redis-backed store and add a
distributed lock around cold-start so two workers can't race to boot the
same org.

This module is intentionally Docker-only for now. When we deploy on Railway
or Modal, write a parallel runtime class and a small factory in get_runtime().
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import docker
import yaml
from docker.errors import NotFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.materialize import materialize_mcp_servers


log = logging.getLogger(__name__)

IMAGE_TAG = "aki-hermes:0.13.0"
CONTAINER_INTERNAL_PORT = 8080


@dataclass
class HermesProcess:
    org_id: UUID
    container_id: str
    host_port: int
    api_key: str                       # bearer the proxy sends to Hermes
    started_at: float
    last_touched: float = field(default_factory=lambda: time.time())

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"

    def touch(self) -> None:
        self.last_touched = time.time()


_REGISTRY: dict[UUID, HermesProcess] = {}
_LOCKS: dict[UUID, asyncio.Lock] = {}


def _lock_for(org_id: UUID) -> asyncio.Lock:
    lock = _LOCKS.get(org_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[org_id] = lock
    return lock


def _pick_free_port() -> int:
    """Bind ephemeral, close, return the port. Race-prone in theory; in
    practice the Docker container claims it within a few ms of cold-start."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _org_dir(org_id: UUID) -> Path:
    settings = get_settings()
    p = Path(settings.hermes_data_dir).expanduser() / str(org_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _materialize_config(db: AsyncSession, org_id: UUID) -> None:
    """Write the per-org config.yaml at $HERMES_DATA_DIR/<org_id>/config.yaml."""
    settings = get_settings()
    mcp_servers_list = await materialize_mcp_servers(db, org_id)

    # The hermes_cli config schema indexes mcp_servers by NAME, not as a list.
    mcp_servers = {entry["name"]: {k: v for k, v in entry.items() if k != "name"}
                   for entry in mcp_servers_list}

    config = {
        "model": {
            "provider": "custom",
            "default": settings.hermes_model_name,
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
        "mcp_servers": mcp_servers,
    }
    cfg_path = _org_dir(org_id) / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(config, sort_keys=False))


async def ensure_running(db: AsyncSession, org_id: UUID) -> HermesProcess:
    """Idempotent: return a running per-org Hermes process, cold-starting if needed."""
    async with _lock_for(org_id):
        proc = _REGISTRY.get(org_id)
        if proc is not None and _container_is_running(proc.container_id):
            proc.touch()
            return proc

        # Materialize config + boot
        await _materialize_config(db, org_id)
        proc = await _boot_container(org_id)
        _REGISTRY[org_id] = proc
        return proc


def _container_is_running(container_id: str) -> bool:
    client = docker.from_env()
    try:
        c = client.containers.get(container_id)
        return c.status == "running"
    except NotFound:
        return False


async def _boot_container(org_id: UUID) -> HermesProcess:
    settings = get_settings()
    client = docker.from_env()
    port = _pick_free_port()
    api_key = secrets.token_urlsafe(32)
    org_dir = _org_dir(org_id)

    # Docker SDK is sync; run in a thread so we don't block the event loop.
    def _run() -> Any:
        return client.containers.run(
            image=IMAGE_TAG,
            name=f"aki-hermes-{org_id}",
            detach=True,
            ports={f"{CONTAINER_INTERNAL_PORT}/tcp": port},
            volumes={str(org_dir.resolve()): {"bind": "/opt/data", "mode": "rw"}},
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
        )

    container = await asyncio.to_thread(_run)

    # Wait for the API server to be ready. Hermes prints
    # "API server listening on http://0.0.0.0:8080" within ~5-10s.
    await _wait_for_api(port, api_key, timeout_s=30)

    return HermesProcess(
        org_id=org_id,
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


async def shutdown(org_id: UUID) -> None:
    """Stop and remove the per-org container. Called by hibernation + shutdown."""
    proc = _REGISTRY.pop(org_id, None)
    if proc is None:
        return
    client = docker.from_env()

    def _stop() -> None:
        try:
            c = client.containers.get(proc.container_id)
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
    to_stop = [
        org_id
        for org_id, proc in _REGISTRY.items()
        if now - proc.last_touched > limit_s
    ]
    for org_id in to_stop:
        log.info("hibernating org=%s", org_id)
        await shutdown(org_id)
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
    for org_id in list(_REGISTRY.keys()):
        try:
            await shutdown(org_id)
        except Exception:
            log.exception("shutdown failed for org=%s", org_id)


async def reap_orphans() -> int:
    """On startup, remove any `aki-hermes-*` containers that aren't in the
    in-memory registry. Handles the case where uvicorn was killed without
    running its lifespan shutdown — those containers would otherwise linger
    forever and block their host ports.

    Returns the count reaped.
    """
    client = docker.from_env()

    def _list_and_kill() -> int:
        n = 0
        for c in client.containers.list(all=True, filters={"name": "aki-hermes-"}):
            try:
                c.stop(timeout=5)
            except Exception:
                pass
            try:
                c.remove(force=True)
                n += 1
            except Exception:
                pass
        return n

    return await asyncio.to_thread(_list_and_kill)
