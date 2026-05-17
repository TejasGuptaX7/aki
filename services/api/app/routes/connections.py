"""Per-org / per-agent SaaS connections (Composio-backed for v1).

Scoping rules (see docs/architecture.md §6):
  - `agent_id` NULL → org-wide, every agent in the org sees this connection.
  - `agent_id` set  → only that agent sees it.

Routes:
  GET    /connections                      list (optionally filter by agent_id)
  POST   /connections/oauth/start          start OAuth, optionally agent-scoped
  GET    /connections/oauth/callback       Composio redirects back here
  POST   /connections/browser/enable       toggle Browser Use Cloud on
  POST   /connections/browser/disable      toggle off
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.composio_client import auth_config_id_for, get_composio_client
from app.config import get_settings
from app.db import session_for_org
from app.limits import limiter
from app.middleware import get_principal, get_session
from app.models import Agent, Connection


log = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["connections"])


def _row_to_json(r: Connection) -> dict:
    return {
        "id": str(r.id),
        "agent_id": str(r.agent_id) if r.agent_id else None,
        "provider": r.provider,
        "status": r.status,
        "scopes": r.scopes,
        "external_account_id": r.external_account_id,
        "created_at": r.created_at.isoformat(),
    }


async def _validate_agent(
    db: AsyncSession, org_id: UUID, agent_id: UUID
) -> Agent:
    """Look up agent, raise 404 if missing / wrong org / deleted."""
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == org_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return agent


@router.get("")
async def list_connections(
    agent_id: UUID | None = Query(
        None,
        description=(
            "if set, return connections visible to this agent "
            "(org-wide ∪ agent-scoped); if absent, return all rows"
        ),
    ),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    q = select(Connection).where(
        Connection.organization_id == principal.organization_id
    )
    if agent_id is not None:
        await _validate_agent(db, principal.organization_id, agent_id)
        # Org-wide (NULL agent_id) ∪ this agent's own
        q = q.where(
            (Connection.agent_id.is_(None)) | (Connection.agent_id == agent_id)
        )
    rows = (await db.execute(q.order_by(Connection.created_at.desc()))).scalars().all()
    return [_row_to_json(r) for r in rows]


@router.post("/oauth/start")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def oauth_start(
    request: Request,
    provider: str = Query(..., min_length=2, max_length=64),
    agent_id: UUID | None = Query(
        None,
        description="agent to scope this connection to; omit for org-wide",
    ),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    settings = get_settings()
    if not settings.composio_api_key:
        raise HTTPException(503, "COMPOSIO_API_KEY not configured")

    if agent_id is not None:
        await _validate_agent(db, principal.organization_id, agent_id)

    redirect = f"{settings.api_base_url}/connections/oauth/callback"
    auth_cfg = auth_config_id_for(provider)
    try:
        link = await get_composio_client().initiate_oauth(
            principal.organization_id, provider, redirect,
            auth_config_id=auth_cfg,
        )
    except Exception as e:
        log.exception("composio initiate_oauth failed for provider=%s", provider)
        raise HTTPException(502, f"upstream OAuth init failed: {e}")

    # Dedupe: cleanup any stale pending rows for this exact scope so the
    # /connect page doesn't accumulate them on repeated click-throughs.
    # Different agents (or org-wide vs per-agent) keep separate pending
    # rows — that's the point of having per-agent scoping.
    delete_stmt = Connection.__table__.delete().where(
        (Connection.organization_id == principal.organization_id)
        & (Connection.provider == provider)
        & (Connection.status == "pending")
        & (
            Connection.agent_id.is_(None) if agent_id is None
            else Connection.agent_id == agent_id
        )
    )
    await db.execute(delete_stmt)
    db.add(
        Connection(
            id=uuid4(),
            organization_id=principal.organization_id,
            agent_id=agent_id,
            provider=provider,
            external_account_id=link.connected_account_id,
            scopes=[],
            config={
                "source": "composio",
                "connected_account_id": link.connected_account_id,
                "auth_config_id": auth_config_id_for(provider),
            },
            status="pending",
        )
    )
    await db.commit()

    return {
        "url": link.redirect_url,
        "connected_account_id": link.connected_account_id,
        "agent_id": str(agent_id) if agent_id else None,
    }


@router.post("/browser/enable", status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def enable_browser(
    request: Request,
    agent_id: UUID | None = Query(
        None,
        description="agent to scope browser harness to; omit for org-wide",
    ),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Toggle Browser Use Cloud on. No OAuth — the API key is ours; per-org
    isolation is Browser Use's session model."""
    if not get_settings().browser_use_api_key:
        raise HTTPException(503, "BROWSER_USE_API_KEY not configured")

    if agent_id is not None:
        await _validate_agent(db, principal.organization_id, agent_id)

    scope_filter = (
        Connection.agent_id.is_(None) if agent_id is None
        else Connection.agent_id == agent_id
    )
    existing = (
        await db.execute(
            select(Connection).where(
                Connection.organization_id == principal.organization_id,
                Connection.provider == "browser",
                scope_filter,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            Connection(
                id=uuid4(),
                organization_id=principal.organization_id,
                agent_id=agent_id,
                provider="browser",
                external_account_id=None,
                scopes=[],
                config={"source": "browser_use"},
                status="active",
            )
        )
    else:
        existing.status = "active"
        existing.config = {**(existing.config or {}), "source": "browser_use"}

    await db.execute(
        text("SELECT pg_notify('org_connections_changed', :oid)"),
        {"oid": str(principal.organization_id)},
    )
    await db.commit()

    return {
        "status": "active",
        "provider": "browser",
        "agent_id": str(agent_id) if agent_id else None,
    }


@router.post("/browser/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_browser(
    agent_id: UUID | None = Query(None),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    scope_filter = (
        Connection.agent_id.is_(None) if agent_id is None
        else Connection.agent_id == agent_id
    )
    existing = (
        await db.execute(
            select(Connection).where(
                Connection.organization_id == principal.organization_id,
                Connection.provider == "browser",
                scope_filter,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.status = "disabled"
        await db.execute(
            text("SELECT pg_notify('org_connections_changed', :oid)"),
            {"oid": str(principal.organization_id)},
        )
        await db.commit()


@router.get("/oauth/callback")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def oauth_callback(
    request: Request,
    connected_account_id: str = Query(...),
    status: str | None = Query(None),
) -> RedirectResponse:
    """Public endpoint — Composio redirects here without our JWT.

    The connected_account_id is opaque and unguessable; we verify with
    Composio (which requires our API key) and recover the user_id (= org_id)
    from the response. We then set the RLS GUC for that org and upsert. The
    agent_id (if any) is preserved from the pending row we created at
    /oauth/start — Composio doesn't echo it back, so we can't recover it
    from the redirect query string.
    """
    if status and status.lower() not in ("success", "ok", ""):
        raise HTTPException(400, f"OAuth failed: status={status}")

    state = await get_composio_client().get_connection(connected_account_id)

    try:
        org_id = UUID(state.user_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "composio returned a non-UUID user_id")

    async with session_for_org(org_id) as db:
        row = (
            await db.execute(
                select(Connection).where(
                    Connection.external_account_id == connected_account_id
                )
            )
        ).scalar_one_or_none()

        if row is None:
            # Orphan callback — no pending row from /oauth/start. Materialize
            # as an org-wide connection so the user isn't stranded with a
            # successful OAuth that has no DB record.
            row = Connection(
                id=uuid4(),
                organization_id=org_id,
                agent_id=None,
                provider=state.toolkit_slug,
                external_account_id=connected_account_id,
                scopes=[],
                config={
                    "source": "composio",
                    "connected_account_id": connected_account_id,
                    "auth_config_id": state.auth_config_id,
                },
                status="active" if state.status == "ACTIVE" else "pending",
            )
            db.add(row)
        else:
            row.status = "active" if state.status == "ACTIVE" else "pending"
            row.provider = state.toolkit_slug or row.provider
            cfg = dict(row.config or {})
            cfg["auth_config_id"] = state.auth_config_id or cfg.get("auth_config_id")
            row.config = cfg
            # agent_id preserved from /oauth/start

        # NOTIFY listeners (the per-org Hermes lifecycle manager) that the
        # connection set changed so they can rebuild per-agent MCP configs.
        await db.execute(
            text("SELECT pg_notify('org_connections_changed', :oid)"),
            {"oid": str(org_id)},
        )
        await db.commit()

    return RedirectResponse(
        url=f"{get_settings().web_base_url.rstrip('/')}/connect?ok=1",
        status_code=302,
    )


def _failed_redirect(message: str) -> RedirectResponse:
    """Bounce the user back to /connect with the error in the query string
    so the UI can render it instead of stranding them on a 500."""
    from urllib.parse import quote
    base = get_settings().web_base_url.rstrip("/")
    return RedirectResponse(url=f"{base}/connect?err={quote(message)}", status_code=302)
