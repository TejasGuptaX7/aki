"""Build the per-(org, dept) mcp.servers[] list for hermes.config.yaml.

Each department gets its own Hermes container with its own MCP server set.
Composio's session is still keyed on org_id (one MCP session per org, shared
across departments) — dept_id only narrows which `connections` rows feed
custom-MCP and browser-use entries.

The control plane never executes tool calls itself — Hermes does, via MCP.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.composio_client import get_composio_client
from app.config import get_settings
from app.models import Connection


async def materialize_mcp_servers(
    db: AsyncSession, org_id: UUID, dept_id: UUID
) -> list[dict[str, Any]]:
    """Return mcp.servers[] entries for this department.

    Composio's MCP URL is session-scoped on org; we call create_session(org_id)
    and inline whatever URL/headers it returns. Custom MCP rows are passed
    through from connection.config verbatim.
    """
    settings = get_settings()
    servers: list[dict[str, Any]] = []

    rows = (
        await db.execute(
            select(Connection).where(Connection.department_id == dept_id)
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

        if source == "browser_use" and not seen_browser and settings.browser_use_api_key:
            servers.append(
                {
                    "name": "browser",
                    "transport": "http",
                    "url": "https://api.browser-use.com/v3/mcp",
                    "headers": {"x-browser-use-api-key": settings.browser_use_api_key},
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
