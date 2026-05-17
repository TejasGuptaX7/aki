"""Per-org SaaS connections (Composio-backed).

Three endpoints:
  - POST /connections/oauth/start?provider=gmail
        Returns a hosted OAuth URL plus a pending connection row.
  - GET  /connections/oauth/callback?connection_id=...
        Composio redirects the user here. We confirm with Composio, mark the
        row active, and NOTIFY org_connections_changed so the per-org Hermes
        runtime reloads its mcp.servers list.
  - GET  /connections
        List connections for the principal's org.
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
from app.models import Connection


log = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("")
async def list_connections(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await db.execute(
            select(Connection)
            .where(Connection.organization_id == principal.organization_id)
            .order_by(Connection.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "provider": r.provider,
            "status": r.status,
            "scopes": r.scopes,
            "external_account_id": r.external_account_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/oauth/start")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def oauth_start(
    request: Request,
    provider: str = Query(..., min_length=2, max_length=64),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    settings = get_settings()
    if not settings.composio_api_key:
        raise HTTPException(503, "COMPOSIO_API_KEY not configured")

    redirect = f"{settings.api_base_url}/connections/oauth/callback"
    auth_config_id = auth_config_id_for(provider)
    link = await get_composio_client().initiate_oauth(
        principal.organization_id, auth_config_id, redirect
    )

    db.add(
        Connection(
            id=uuid4(),
            organization_id=principal.organization_id,
            provider=provider,
            external_account_id=link.connected_account_id,
            scopes=[],
            config={
                "source": "composio",
                "connected_account_id": link.connected_account_id,
                "auth_config_id": auth_config_id,
            },
            status="pending",
        )
    )
    await db.commit()

    return {
        "url": link.redirect_url,
        "connected_account_id": link.connected_account_id,
    }


@router.get("/oauth/callback")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def oauth_callback(
    request: Request,
    connected_account_id: str = Query(...),
    status: str | None = Query(None),
) -> RedirectResponse:
    """Public endpoint — Composio redirects here without our JWT.

    The connected_account_id is opaque and unguessable; we verify with Composio
    (which requires our API key) and recover the user_id (= org_id) from the
    response. Then we set the RLS GUC for that org and upsert.
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
            row = Connection(
                id=uuid4(),
                organization_id=org_id,
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

        # NOTIFY listeners (the per-org Hermes lifecycle manager) that the
        # connection set changed so they can rebuild mcp.servers.
        await db.execute(
            text("SELECT pg_notify('org_connections_changed', :oid)"),
            {"oid": str(org_id)},
        )
        await db.commit()

    return RedirectResponse(
        url=f"{get_settings().web_base_url.rstrip('/')}/chat", status_code=302,
    )
