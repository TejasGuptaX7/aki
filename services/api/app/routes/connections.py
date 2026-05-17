"""Per-org / per-agent SaaS connections.

Scoping rules (see docs/architecture.md §6):
  - `agent_id` NULL → org-wide, every agent in the org sees this connection.
  - `agent_id` set  → only that agent sees it.

Routes:
  GET    /connections                            list (optional agent_id filter)
  POST   /connections/pipedream/connect-token    issue a Pipedream Connect Token
  POST   /connections/pipedream/record           record a successful Pipedream OAuth
  POST   /connections/browser/enable             toggle Browser Use Cloud on
  POST   /connections/browser/disable            toggle off
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field, field_validator

from app.auth import Principal
from app.config import get_settings
from app.limits import limiter
from app.middleware import get_principal, get_session
from app.models import Agent, Connection
from app.pipedream_client import PipedreamError, get_pipedream_client


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


# ─────────────────────────────────────────────────────────────────────────────
# Pipedream Connect endpoints — the white-label OAuth path.
#
# Flow:
#   1. Frontend calls POST /connections/pipedream/connect-token (this file)
#      → backend returns { token, external_user_id, project_id, environment }
#   2. Frontend uses Pipedream's JS SDK with that token to open the connect
#      modal — OAuth happens on the provider's domain, branded "Aki"
#   3. On SDK success callback, frontend POSTs to /connections/pipedream/record
#      with the resulting account_id
#   4. Backend creates a Connection row with source=pipedream and NOTIFY's
#      so per-org Hermes profiles rematerialize
# ─────────────────────────────────────────────────────────────────────────────


class PipedreamConnectTokenRequest(BaseModel):
    agent_id: UUID | None = None


class PipedreamRecordRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=255)
    app_slug: str = Field(min_length=1, max_length=64)
    external_user_id: str = Field(min_length=1, max_length=255)
    agent_id: UUID | None = None

    @field_validator("app_slug")
    @classmethod
    def _slug_normalized(cls, v: str) -> str:
        return v.strip().lower()


@router.post("/pipedream/connect-token")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def pipedream_connect_token(
    request: Request,
    body: PipedreamConnectTokenRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Issue a Pipedream Connect Token the frontend SDK uses to start OAuth.

    The token authorizes ONE end-user to connect accounts under our
    project. We choose the external_user_id ourselves to keep Pipedream's
    notion of "user" aligned with our (org_id) or (org_id, agent_id)
    scopes.
    """
    settings = get_settings()
    if not (settings.pipedream_client_id and settings.pipedream_client_secret):
        raise HTTPException(503, "Pipedream Connect not configured")
    if body.agent_id is not None:
        await _validate_agent(db, principal.organization_id, body.agent_id)

    eu = (
        str(principal.organization_id)
        if body.agent_id is None
        else f"{principal.organization_id}:{body.agent_id}"
    )
    pd = get_pipedream_client()
    try:
        d = await pd.create_connect_token(
            external_user_id=eu,
            allowed_origins=[settings.web_base_url.rstrip("/")],
            success_redirect_uri=f"{settings.web_base_url.rstrip('/')}/connect?ok=1",
            error_redirect_uri=f"{settings.web_base_url.rstrip('/')}/connect?err=oauth_failed",
        )
    except PipedreamError as e:
        log.exception("pipedream create_connect_token failed")
        raise HTTPException(502, f"upstream: {e}")

    return {
        "token": d.get("token") or d.get("connect_token"),
        "expires_at": d.get("expires_at"),
        # connect_link_url is the hosted-OAuth fallback — frontend can either
        # use the JS SDK with `token`, OR redirect the user straight to this
        # URL. The hosted flow is simpler; SDK is needed only for embedding
        # the consent modal inside our own UI.
        "connect_link_url": d.get("connect_link_url"),
        "external_user_id": eu,
        "project_id": settings.pipedream_project_id,
        "environment": settings.pipedream_environment,
        "agent_id": str(body.agent_id) if body.agent_id else None,
    }


@router.post("/pipedream/record", status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def pipedream_record(
    request: Request,
    body: PipedreamRecordRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Record a successful Pipedream OAuth. The frontend SDK fires its
    `onConnect` callback with an account_id; the frontend POSTs that here
    along with the metadata we issued at /connect-token time.

    Verification: we re-fetch the account from Pipedream's API by id, both
    to confirm it exists and to read the canonical app slug + state. A
    spoofed POST would fail this check."""
    settings = get_settings()
    if not (settings.pipedream_client_id and settings.pipedream_client_secret):
        raise HTTPException(503, "Pipedream Connect not configured")
    if body.agent_id is not None:
        await _validate_agent(db, principal.organization_id, body.agent_id)

    # Authz: external_user_id must match the principal's expected scope.
    expected_eu = (
        str(principal.organization_id)
        if body.agent_id is None
        else f"{principal.organization_id}:{body.agent_id}"
    )
    if body.external_user_id != expected_eu:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "external_user_id does not match the principal's scope",
        )

    pd = get_pipedream_client()
    try:
        account = await pd.get_account(body.account_id)
    except PipedreamError as e:
        log.exception("pipedream get_account failed account=%s", body.account_id)
        raise HTTPException(502, f"upstream account verify failed: {e}")

    # Pipedream may return either the app slug as `name_slug` (newer) or
    # under `app.name_slug` (older). Accept both.
    canonical_app = (
        account.get("name_slug")
        or (account.get("app") or {}).get("name_slug")
        or body.app_slug
    )

    existing = await db.scalar(
        select(Connection).where(
            Connection.organization_id == principal.organization_id,
            Connection.external_account_id == body.account_id,
        )
    )
    if existing is not None:
        existing.status = "active"
        existing.agent_id = body.agent_id
        existing.provider = canonical_app
        existing.config = {
            **(existing.config or {}),
            "source": "pipedream",
            "account_id": body.account_id,
            "external_user_id": expected_eu,
            "app_slug": canonical_app,
        }
        row = existing
    else:
        row = Connection(
            id=uuid4(),
            organization_id=principal.organization_id,
            agent_id=body.agent_id,
            provider=canonical_app,
            external_account_id=body.account_id,
            scopes=[],
            config={
                "source": "pipedream",
                "account_id": body.account_id,
                "external_user_id": expected_eu,
                "app_slug": canonical_app,
            },
            status="active",
        )
        db.add(row)

    await db.execute(
        text("SELECT pg_notify('org_connections_changed', :oid)"),
        {"oid": str(principal.organization_id)},
    )
    await db.commit()
    return _row_to_json(row)
