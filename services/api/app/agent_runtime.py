"""Per-org Hermes container with per-agent profiles inside.

Architecture (see docs/architecture.md §5):

  ┌─────────────────────  one Docker container per org  ──────────────────────┐
  │                                                                          │
  │    supervisor.py (HTTP server on port 8080)                              │
  │      ├─ reads /opt/data/manifest.json (agent_id → internal_port)        │
  │      ├─ spawns one `hermes -p <agent_id> gateway run` per agent          │
  │      └─ proxies /v1/* by X-Aki-Agent-Id header to the right profile      │
  │                                                                          │
  │    profile aki-sales        profile aki-recruiting     profile aki        │
  │      hermes on :9001          hermes on :9002          hermes on :9003   │
  │      $HERMES_HOME=                                                       │
  │       /opt/data/agents/<aid>/                                            │
  │                                                                          │
  └──────────────────────────────────────────────────────────────────────────┘

State (org_id → OrgContainer) is in-memory in this process. For multi-worker
production, swap _REGISTRY for a Redis-backed store and add a distributed
lock around cold-start so two workers can't race to boot the same org.

Lifecycle:
  ensure_org_container — idempotent cold-start (~10s) with per-org asyncio
                         lock. Reuses warm containers.
  ensure_agent_loaded  — idempotent profile-load inside a running container;
                         appends to manifest + asks supervisor to reload.
  hibernation_loop     — background task; stops containers idle > N min.
  reap_orphans         — on startup, kills any `aki-hermes-*` container not
                         in the in-memory registry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import docker
import httpx
import yaml
from docker.errors import NotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.materialize import materialize_mcp_servers
from app.models import Agent


log = logging.getLogger(__name__)

IMAGE_TAG = "aki-hermes:0.13.0"
SUPERVISOR_INTERNAL_PORT = 8080
# Range each container's supervisor uses for per-agent Hermes profiles.
# 100 slots per org is far more than we'll ever need; the supervisor
# allocates from the low end and recycles freed ports.
PROFILE_PORT_RANGE = (9001, 9100)


@dataclass
class OrgContainer:
    """One per-org Docker container. The supervisor inside owns all the
    per-agent Hermes processes; we only know about it externally as a single
    host:port that speaks the supervisor's protocol."""

    org_id: UUID
    container_id: str
    host_port: int
    supervisor_api_key: str
    started_at: float
    last_touched: float = field(default_factory=lambda: time.time())
    # agent_id strings (str(UUID)) that we've loaded into this container.
    # The supervisor is the source of truth; this is a local cache to avoid
    # asking on every chat request.
    loaded_agents: set[str] = field(default_factory=set)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"

    def touch(self) -> None:
        self.last_touched = time.time()


_REGISTRY: dict[UUID, OrgContainer] = {}
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
    (p / "agents").mkdir(exist_ok=True)
    return p


def _agent_dir(org_id: UUID, agent_id: UUID) -> Path:
    p = _org_dir(org_id) / "agents" / str(agent_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─── Manifest: control plane → supervisor handshake ─────────────────────────


async def _read_agents_for_org(db: AsyncSession, org_id: UUID) -> list[Agent]:
    rows = (
        await db.execute(
            select(Agent).where(
                Agent.organization_id == org_id,
                Agent.status == "active",
            )
        )
    ).scalars().all()
    return list(rows)


def _write_manifest(org_id: UUID, agents: list[Agent]) -> Path:
    """Write the org's manifest (agents the supervisor should keep loaded).
    Atomic: write to .tmp then rename so the supervisor never reads a
    half-written file."""
    org_dir = _org_dir(org_id)
    manifest_path = org_dir / "manifest.json"
    tmp_path = manifest_path.with_suffix(".tmp")

    payload = {
        "agents": [
            {
                "id": str(a.id),
                "slug": a.slug,
                "system_prompt": a.system_prompt,
            }
            for a in agents
        ],
    }
    tmp_path.write_text(json.dumps(payload, indent=2))
    tmp_path.replace(manifest_path)
    return manifest_path


async def _seed_agent_workspace(
    db: AsyncSession, org_id: UUID, agent: Agent
) -> None:
    """Create the per-agent workspace dir and the per-profile Hermes config.

    Each Hermes profile loads its config from $HERMES_HOME/config.yaml at
    `hermes -p <agent_id>` start. The mcp_servers dict is materialized from
    the agent's visible connections (org-wide ∪ per-agent) — see
    app/connectors/materialize.py for the visibility rules.

    Hermes 0.13's config schema keys mcp_servers by name (not as a list),
    so we collapse the list to a dict here.
    """
    settings = get_settings()
    agent_dir = _agent_dir(org_id, agent.id)
    config_path = agent_dir / "config.yaml"

    server_list = await materialize_mcp_servers(db, org_id, agent.id)
    mcp_servers = {
        entry["name"]: {k: v for k, v in entry.items() if k != "name"}
        for entry in server_list
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))


# ─── Container lifecycle ────────────────────────────────────────────────────


async def ensure_org_container(db: AsyncSession, org_id: UUID) -> OrgContainer:
    """Idempotent: return a running per-org container, cold-starting if needed."""
    async with _lock_for(org_id):
        proc = _REGISTRY.get(org_id)
        if proc is not None and _container_is_running(proc.container_id):
            proc.touch()
            return proc

        # Sync manifest with current DB state before booting
        agents = await _read_agents_for_org(db, org_id)
        for a in agents:
            await _seed_agent_workspace(db, org_id, a)
        _write_manifest(org_id, agents)

        proc = await _boot_container(org_id)
        proc.loaded_agents = {str(a.id) for a in agents}
        _REGISTRY[org_id] = proc
        return proc


async def ensure_agent_loaded(
    db: AsyncSession, org_id: UUID, agent_id: UUID
) -> OrgContainer:
    """Idempotent: ensure the org container is running AND has this agent
    profile loaded. Returns the container.

    If the agent isn't in the supervisor's manifest yet (e.g. created after
    the container booted), update the manifest and ask the supervisor to
    reload before returning.
    """
    container = await ensure_org_container(db, org_id)
    aid = str(agent_id)
    if aid in container.loaded_agents:
        container.touch()
        return container

    async with _lock_for(org_id):
        # Re-check under lock; another request may have loaded it.
        if aid in container.loaded_agents:
            container.touch()
            return container

        agent = (
            await db.execute(
                select(Agent).where(
                    Agent.id == agent_id,
                    Agent.organization_id == org_id,
                    Agent.status == "active",
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise RuntimeError(
                f"agent {agent_id} not found or not active in org {org_id}"
            )

        await _seed_agent_workspace(db, org_id, agent)
        agents = await _read_agents_for_org(db, org_id)
        _write_manifest(org_id, agents)
        await _supervisor_reload(container)
        container.loaded_agents = {str(a.id) for a in agents}
        container.touch()
        return container


async def _supervisor_reload(container: OrgContainer) -> None:
    """Tell the supervisor to re-read manifest.json and converge subprocesses."""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(
            f"{container.base_url}/control/reload",
            headers={"Authorization": f"Bearer {container.supervisor_api_key}"},
        )
        r.raise_for_status()


def _container_is_running(container_id: str) -> bool:
    client = docker.from_env()
    try:
        c = client.containers.get(container_id)
        return c.status == "running"
    except NotFound:
        return False


async def _boot_container(org_id: UUID) -> OrgContainer:
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
            ports={f"{SUPERVISOR_INTERNAL_PORT}/tcp": port},
            volumes={str(org_dir.resolve()): {"bind": "/opt/data", "mode": "rw"}},
            environment={
                "HERMES_HOME": "/opt/data",
                "HOME": "/opt/data",
                "OPENAI_API_KEY": settings.openai_api_key or "",
                "SUPERVISOR_HOST": "0.0.0.0",
                "SUPERVISOR_PORT": str(SUPERVISOR_INTERNAL_PORT),
                "SUPERVISOR_API_KEY": api_key,
                "PROFILE_PORT_LOW": str(PROFILE_PORT_RANGE[0]),
                "PROFILE_PORT_HIGH": str(PROFILE_PORT_RANGE[1]),
            },
            auto_remove=False,
            restart_policy={"Name": "no"},
        )

    container = await asyncio.to_thread(_run)

    # Wait for supervisor + all profiles in the manifest to be ready. Each
    # Hermes profile cold-starts in 5-10s; with 1-3 profiles serialized on
    # container CPU, 45s is a comfortable ceiling.
    await _wait_for_supervisor(port, api_key, timeout_s=45)

    return OrgContainer(
        org_id=org_id,
        container_id=container.id,
        host_port=port,
        supervisor_api_key=api_key,
        started_at=time.time(),
    )


async def _wait_for_supervisor(port: int, api_key: str, *, timeout_s: float) -> None:
    """Poll /control/health until the supervisor reports all-profiles-ready."""
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    last_body: str | None = None
    async with httpx.AsyncClient(timeout=2.0) as c:
        while time.time() < deadline:
            try:
                r = await c.get(
                    f"http://127.0.0.1:{port}/control/health",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if r.status_code == 200:
                    body = r.json()
                    if body.get("ready") is True:
                        return
                    last_body = json.dumps(body)
            except Exception as e:
                last_err = e
            await asyncio.sleep(0.5)
    raise RuntimeError(
        f"supervisor at :{port} not ready within {timeout_s}s "
        f"(last_body={last_body!r}, last_err={last_err!r})"
    )


# ─── Shutdown / hibernation / reaper ────────────────────────────────────────


async def shutdown(org_id: UUID) -> None:
    """Stop and remove the per-org container."""
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
    """Stop containers idle longer than `idle_minutes`. Returns count stopped.

    Hibernation is per-CONTAINER, not per-agent. If any agent in an org has
    been touched recently, the whole container stays warm. Right tradeoff:
    the container is the unit of cost; per-agent idle tracking adds
    complexity without obvious savings.
    """
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
    """On startup, remove any `aki-hermes-*` containers not in the in-memory
    registry. Handles uvicorn crashes that skipped lifespan shutdown."""
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
