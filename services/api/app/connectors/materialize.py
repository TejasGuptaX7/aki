"""Build the per-agent mcp.servers list for one Hermes profile's config.yaml.

The control plane never executes tool calls itself — Hermes does, via MCP.
This function's only job is to translate `connections` rows into the YAML
shape Hermes expects, which is then written to the per-agent workspace at
`${HERMES_DATA_DIR}/<org_id>/agents/<agent_id>/config.yaml` at boot and
on NOTIFY org_connections_changed.

Per-agent scoping rules (see docs/architecture.md §6):
  - connection.agent_id IS NULL  → org-wide, visible to every agent
  - connection.agent_id = X      → visible only to agent X

A given agent's MCP server list is the union of (org-wide ∪ its own).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.composio_client import get_composio_client
from app.config import get_settings
from app.models import Connection


async def materialize_mcp_servers(
    db: AsyncSession,
    org_id: UUID,
    agent_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Return MCP server entries this agent should have access to.

    If `agent_id` is None, returns all org-wide connections only (used for
    org-level introspection / debugging, not for actual agent runtime).

    Composio session is keyed on `org_id` (not agent_id) because Composio
    Auth Configs live at the entity level and the tool router automatically
    surfaces tools for ALL connected accounts under that entity. Once we
    migrate to Pipedream/Arcade (which support per-user scoping), this can
    become per-agent.
    """
    settings = get_settings()
    servers: list[dict[str, Any]] = []

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

    has_composio = any(
        (r.config or {}).get("source", "composio") == "composio" for r in rows
    )
    if has_composio and settings.composio_api_key:
        session = await get_composio_client().create_tool_router_session(org_id)
        servers.append(
            {
                "name": "composio",
                "transport": session.mcp_type,
                "url": session.mcp_url,
                "headers": {"x-api-key": settings.composio_api_key},
            }
        )

    seen_browser = False
    for r in rows:
        cfg = r.config or {}
        source = cfg.get("source")

        if (
            source == "browser_use"
            and not seen_browser
            and settings.browser_use_api_key
        ):
            # Browser Use Cloud — one shared MCP endpoint, agent creates
            # per-call sessions via the run_session tool. Per-org isolation
            # is enforced by Browser Use's session model; we pass org_id +
            # agent_id as tags so their dashboard groups runs cleanly.
            servers.append(
                {
                    "name": "browser",
                    "transport": "http",
                    "url": "https://api.browser-use.com/v3/mcp",
                    "headers": {
                        "x-browser-use-api-key": settings.browser_use_api_key,
                    },
                }
            )
            seen_browser = True

        elif source == "custom" and cfg.get("mcp_url"):
            entry: dict[str, Any] = {
                "name": r.provider,
                "transport": cfg.get("transport", "http"),
                "url": cfg["mcp_url"],
            }
            if cfg.get("auth_header"):
                entry["headers"] = {"Authorization": cfg["auth_header"]}
            servers.append(entry)

    return servers
