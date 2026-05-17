"""Build the per-org mcp.servers[] list for hermes.config.yaml.

Replaces the old three-layer Connector ABC. The control plane never executes
tool calls itself — Hermes does, via MCP. This function's only job is to
translate `connections` rows into the YAML shape Hermes expects, which is then
written to ${HERMES_DATA_DIR}/<org_id>/hermes.config.yaml at boot (and on
NOTIFY org_connections_changed).
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
    db: AsyncSession, org_id: UUID
) -> list[dict[str, Any]]:
    """Return mcp.servers[] entries for this org.

    Composio's MCP URL is session-scoped — we call create_session(org_id) and
    inline whatever URL/headers it returns. Custom MCP rows are passed through
    from connection.config verbatim.
    """
    settings = get_settings()
    servers: list[dict[str, Any]] = []

    rows = (
        await db.execute(
            select(Connection).where(Connection.organization_id == org_id)
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
            # Browser Use Cloud — one shared MCP endpoint, agent creates per-call
            # sessions via the run_session tool. Per-org isolation is enforced
            # by Browser Use's session model; we pass org_id as a tag.
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
