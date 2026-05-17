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
  - "{provider}_native"  → native OAuth (Gmail, Slack, Notion, Linear,
                            HubSpot). Tools served from our own MCP server
                            at /agent_internal/native_mcp.
  - "arcade"             → Arcade.dev's managed MCP gateway; per-user via
                            the Arcade-User-ID header.
  - "browser_harness"    → self-hosted services/browser-harness; see
                            PROTOCOL.md
  - "browser_use"        → Browser Use Cloud (fallback)
  - "custom"             → BYO MCP URL, passed through verbatim

Legacy rows with source="pipedream" or source="composio" are skipped and
marked stale; users re-connect via native (top-5) or Arcade (rest). The
DB doesn't get touched here — see app/connectors/__init__.py for the
deprecation marker run by `make` recipes.
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


log = logging.getLogger(__name__)


# Identifiers we hand to Arcade as `Arcade-User-ID`. Org-wide connections
# live under the org id; per-agent under `<org>:<agent>`. Same shape that
# /oauth/arcade/verifier expects in `_resolve_user`.
def _arcade_user_id(org_id: UUID, agent_id: UUID | None) -> str:
    return str(org_id) if agent_id is None else f"{org_id}:{agent_id}"


# Sources we recognize as native (= served by /agent_internal/native_mcp).
NATIVE_SOURCES = frozenset(
    {
        "gmail_native",
        "slack_native",
        "notion_native",
        "linear_native",
        "hubspot_native",
    }
)


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

    `agent_service_token`, when provided, adds the internal MCP servers
    (request_approval + native tools) pointing at our control plane. Caller
    is responsible for minting / persisting the token (see
    agent_runtime._seed_agent_workspace).

    Any service whose env config is missing is silently skipped — local dev
    boxes don't have to set every key to boot.
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

    sources = {(r.config or {}).get("source") for r in rows}

    # ── Internal MCP: request_approval ─────────────────────────────────────
    # Always present when we have a token + an agent context. This is the
    # consent gate: the agent calls this before any tier-2 action and waits
    # for the user's yes/no via /approvals.
    if agent_id is not None and agent_service_token:
        common_headers = {
            "Authorization": f"Bearer {agent_service_token}",
            "X-Aki-Org-Id": str(org_id),
            "X-Aki-Agent-Id": str(agent_id),
        }
        servers.append(
            {
                "name": "approvals",
                "transport": "http",
                "url": f"{settings.api_internal_url.rstrip('/')}/agent_internal/mcp",
                "headers": common_headers,
            }
        )

        # ── Internal MCP: native-provider tools ────────────────────────
        # Only emit if the agent actually has at least one native
        # connection in scope. Hermes will still happily list tools from
        # an MCP server that returns zero, but skipping saves a startup
        # round-trip per orphan agent.
        if any((r.config or {}).get("source") in NATIVE_SOURCES for r in rows):
            servers.append(
                {
                    "name": "native",
                    "transport": "http",
                    "url": f"{settings.api_internal_url.rstrip('/')}/agent_internal/native_mcp",
                    "headers": common_headers,
                }
            )

    org_wide_rows = [r for r in rows if r.agent_id is None]
    agent_rows = [r for r in rows if agent_id is not None and r.agent_id == agent_id]

    # ── Arcade.dev ─────────────────────────────────────────────────────────
    # Single MCP gateway URL; per-user scoping via Arcade-User-ID header.
    # We add separate org-wide vs per-agent entries because they need
    # different headers — Hermes treats them as independent servers.
    if (
        "arcade" in sources
        and settings.arcade_api_key
        and settings.arcade_mcp_gateway_slug
    ):
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

    # Legacy "pipedream" / "composio" sources: ignored silently. Users
    # whose rows still carry those will see the connector disappear from
    # the agent's tool surface and must re-connect via the native or
    # arcade flows. Surfacing that nudge is the frontend's job.

    return servers
