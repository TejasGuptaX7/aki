"""Build the per-agent mcp_servers list for one Hermes profile's config.yaml.

The control plane never executes tool calls itself — Hermes does, via MCP.
This function's only job is to translate `connections` rows + global service
config into the list Hermes expects, written to the per-agent workspace at
`${HERMES_DATA_DIR}/<org_id>/agents/<agent_id>/config.yaml` at boot.

Per-agent scoping rules (see docs/architecture.md §6):
  - connection.agent_id IS NULL  → org-wide, visible to every agent
  - connection.agent_id = X      → visible only to agent X

A given agent's MCP server list is the union of (org-wide ∪ its own).

Source kinds (`connection.config.source`):
  - "pipedream"       → Pipedream Connect; one MCP server per external_user
                        (org-wide and per-agent get separate entries)
  - "arcade"          → Arcade.dev; one MCP server, per-user via header
  - "browser_harness" → self-hosted services/browser-harness; see PROTOCOL.md
  - "browser_use"     → Browser Use Cloud (kept as fallback)
  - "custom"          → BYO MCP URL, passed through verbatim

Legacy rows with `source="composio"` are silently skipped (no MCP server
emitted). The Composio client + auth_config plumbing was deleted in
phase 3d; existing rows live in the DB until the user re-OAuths via
Pipedream and either we expose a /connections DELETE or they ignore the
orphan.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.arcade_client import get_arcade_client
from app.config import get_settings
from app.models import Connection
from app.pipedream_client import get_pipedream_client


log = logging.getLogger(__name__)


def _arcade_user_id(org_id: UUID, agent_id: UUID | None) -> str:
    """Per-user identifier we hand to Arcade. Org-wide connections live
    under the org id; per-agent under `<org>:<agent>`."""
    return str(org_id) if agent_id is None else f"{org_id}:{agent_id}"


def _pipedream_external_user_id(org_id: UUID, agent_id: UUID | None) -> str:
    """Per-user identifier we hand to Pipedream Connect. Same shape as Arcade."""
    return str(org_id) if agent_id is None else f"{org_id}:{agent_id}"


async def materialize_mcp_servers(
    db: AsyncSession,
    org_id: UUID,
    agent_id: UUID | None = None,
    *,
    agent_service_token: str | None = None,
) -> list[dict[str, Any]]:
    """Return MCP server entries this agent should have access to.

    If `agent_id` is None, returns only org-wide entries (for debugging /
    org-level introspection). Per-agent calls return the union of org-wide
    + agent-scoped.

    `agent_service_token`, when provided, adds the request_approval MCP
    server pointing at our control plane's /agent_internal/mcp endpoint.
    Caller is responsible for minting / persisting the token (see
    agent_runtime._seed_agent_workspace).

    Any service whose env config is missing is silently skipped — local dev
    boxes don't have to set every key to boot.
    """
    settings = get_settings()
    servers: list[dict[str, Any]] = []

    # ── request_approval (internal MCP) ────────────────────────────────────
    # Always present when we have a token + an agent context. This is the
    # consent gate: the agent calls this before any tier-2 action and waits
    # for the user's yes/no via /approvals.
    if agent_id is not None and agent_service_token:
        servers.append(
            {
                "name": "approvals",
                "transport": "http",
                "url": f"{settings.api_internal_url.rstrip('/')}/agent_internal/mcp",
                "headers": {
                    "Authorization": f"Bearer {agent_service_token}",
                    "X-Aki-Org-Id": str(org_id),
                    "X-Aki-Agent-Id": str(agent_id),
                },
            }
        )

    visibility = (
        (Connection.agent_id.is_(None))
        if agent_id is None
        else or_(Connection.agent_id.is_(None), Connection.agent_id == agent_id)
    )

    rows = (
        await db.execute(
            select(Connection).where(
                Connection.organization_id == org_id,
                Connection.status == "active",
                visibility,
            )
        )
    ).scalars().all()

    sources = {(r.config or {}).get("source") for r in rows}
    org_wide_rows = [r for r in rows if r.agent_id is None]
    agent_rows = [r for r in rows if agent_id is not None and r.agent_id == agent_id]

    # ── Pipedream Connect ──────────────────────────────────────────────────
    # One MCP endpoint per (project, external_user). We add one for the
    # org-wide entity if there's any org-wide Pipedream connection, and a
    # separate one for the per-agent entity if there's any agent-scoped one.
    # Hermes sees both as independent MCP servers and surfaces tools from
    # the union — exactly what we want for the (org-wide ∪ per-agent) rule.
    if "pipedream" in sources and settings.pipedream_client_id:
        try:
            pd = get_pipedream_client()
            mcp_headers = await pd.mcp_headers()
            if any((r.config or {}).get("source") == "pipedream" for r in org_wide_rows):
                eu = _pipedream_external_user_id(org_id, None)
                servers.append(
                    {
                        "name": "pipedream-org",
                        "transport": "http",
                        "url": pd.mcp_url(eu),
                        "headers": mcp_headers,
                    }
                )
            if agent_id is not None and any(
                (r.config or {}).get("source") == "pipedream" for r in agent_rows
            ):
                eu = _pipedream_external_user_id(org_id, agent_id)
                servers.append(
                    {
                        "name": "pipedream-agent",
                        "transport": "http",
                        "url": pd.mcp_url(eu),
                        "headers": mcp_headers,
                    }
                )
        except Exception:
            log.exception("pipedream MCP materialize failed; skipping")

    # ── Arcade.dev ─────────────────────────────────────────────────────────
    # Single MCP endpoint; per-user scoping via X-Arcade-User-Id header.
    # We add separate org-wide vs per-agent entries because they need
    # different headers — Hermes treats them as independent servers.
    if "arcade" in sources and settings.arcade_api_key:
        try:
            ac = get_arcade_client()
            if any((r.config or {}).get("source") == "arcade" for r in org_wide_rows):
                servers.append(
                    {
                        "name": "arcade-org",
                        "transport": "http",
                        "url": ac.mcp_url(),
                        "headers": ac.mcp_headers(_arcade_user_id(org_id, None)),
                    }
                )
            if agent_id is not None and any(
                (r.config or {}).get("source") == "arcade" for r in agent_rows
            ):
                servers.append(
                    {
                        "name": "arcade-agent",
                        "transport": "http",
                        "url": ac.mcp_url(),
                        "headers": ac.mcp_headers(_arcade_user_id(org_id, agent_id)),
                    }
                )
        except Exception:
            log.exception("arcade MCP materialize failed; skipping")

    # ── Self-hosted Browser Harness ────────────────────────────────────────
    # See services/browser-harness/PROTOCOL.md for the wire contract.
    # X-Aki-Agent-Id is set statically per-profile here (NOT per-call by
    # Hermes); each agent profile has its own materialized config, so the
    # static header is correctly scoped.
    if (
        "browser_harness" in sources
        and settings.browser_harness_url
        and settings.browser_harness_api_key
    ):
        headers = {
            "Authorization": f"Bearer {settings.browser_harness_api_key}",
            "X-Aki-Org-Id": str(org_id),
        }
        if agent_id is not None:
            headers["X-Aki-Agent-Id"] = str(agent_id)
        servers.append(
            {
                "name": "browser",
                "transport": "http",
                "url": f"{settings.browser_harness_url.rstrip('/')}/mcp",
                "headers": headers,
            }
        )

    # ── Browser Use Cloud (fallback) ───────────────────────────────────────
    elif "browser_use" in sources and settings.browser_use_api_key:
        # Else-if because if both are connected, prefer the self-hosted one.
        # The agent shouldn't see two browser MCPs competing.
        servers.append(
            {
                "name": "browser",
                "transport": "http",
                "url": "https://api.browser-use.com/v3/mcp",
                "headers": {"x-browser-use-api-key": settings.browser_use_api_key},
            }
        )

    # ── Custom BYO MCP ─────────────────────────────────────────────────────
    for r in rows:
        cfg = r.config or {}
        if cfg.get("source") == "custom" and cfg.get("mcp_url"):
            entry: dict[str, Any] = {
                "name": r.provider,
                "transport": cfg.get("transport", "http"),
                "url": cfg["mcp_url"],
            }
            if cfg.get("auth_header"):
                entry["headers"] = {"Authorization": cfg["auth_header"]}
            servers.append(entry)

    return servers
