"""Per-org / per-agent SaaS connections.

Scoping rules (see docs/architecture.md §6):
  - `agent_id` NULL → org-wide, every agent in the org sees this connection.
  - `agent_id` set  → only that agent sees it.

Routes:
  GET    /connections                              list (optional agent filter)
  POST   /connections/oauth/start?provider=…       kick off native OAuth
  GET    /connections/oauth/callback               provider redirect target
  POST   /connections/arcade/start?provider=…      kick off Arcade-managed OAuth
  GET    /connections/arcade/status?auth_id=…      poll Arcade auth status
  POST   /connections/arcade/record                record a completed Arcade auth
  POST   /connections/browser/enable               toggle Browser Use Cloud on
  POST   /connections/browser/disable              toggle off
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.arcade_client import ArcadeError, get_arcade_client
from app.auth import Principal
from app.config import get_settings
from app.db import session_for_org
from app.limits import limiter
from app.middleware import get_principal, get_session
from app.models import Agent, Connection
from app.oauth import NATIVE_HANDLERS, NativeOAuthError, get_handler


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
        "source": (r.config or {}).get("source"),
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
        q = q.where(
            (Connection.agent_id.is_(None)) | (Connection.agent_id == agent_id)
        )
    rows = (await db.execute(q.order_by(Connection.created_at.desc()))).scalars().all()
    return [_row_to_json(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Browser Use Cloud — single shared API key, just a row toggle. No OAuth.
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/browser/enable", status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def enable_browser(
    request: Request,
    agent_id: UUID | None = Query(
        None, description="agent to scope browser harness to; omit for org-wide"
    ),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
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
# Native OAuth — our own OAuth client per provider, no connector platform.
#
# Flow:
#   1. Frontend POSTs /connections/oauth/start?provider=gmail → returns
#      { auth_url, state }
#   2. Frontend redirects window.location → auth_url
#   3. Provider redirects user back to ${WEB_BASE_URL}/connect/oauth/callback
#      ?code=...&state=...
#   4. That frontend page extracts code + state and POSTs to
#      /connections/oauth/callback
#   5. Backend exchanges code → tokens, upserts Connection, NOTIFY's so
#      per-org Hermes profiles rematerialize.
# ─────────────────────────────────────────────────────────────────────────────


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str
    provider: str
    agent_id: UUID | None = None


@router.post("/oauth/start", response_model=OAuthStartResponse)
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def oauth_start(
    request: Request,
    provider: str = Query(..., description="One of: gmail, slack, notion, linear, hubspot"),
    agent_id: UUID | None = Query(None),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> OAuthStartResponse:
    """Kick off native OAuth. Returns the consent URL the frontend redirects
    the user to."""
    if provider not in NATIVE_HANDLERS:
        raise HTTPException(
            400,
            f"unsupported provider; native handlers: {sorted(NATIVE_HANDLERS)}",
        )
    if agent_id is not None:
        await _validate_agent(db, principal.organization_id, agent_id)

    handler = get_handler(provider)
    try:
        out = await handler.start_auth(
            org_id=principal.organization_id,
            agent_id=agent_id,
            db=db,
        )
        await db.commit()
    except NativeOAuthError as e:
        log.exception("native oauth start failed provider=%s", provider)
        raise HTTPException(503, f"oauth start failed: {e}")

    return OAuthStartResponse(
        auth_url=out["auth_url"],
        state=out["state"],
        provider=provider,
        agent_id=agent_id,
    )


class OAuthCallbackBody(BaseModel):
    """Frontend forwards the provider's redirect into a JSON POST so we
    don't have to set cookies or rely on Referer."""
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=4096)


@router.post("/oauth/callback", status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def oauth_callback(
    request: Request,
    body: OAuthCallbackBody,
) -> dict:
    """Exchange the OAuth code for a token and persist the Connection.

    Note: NO `principal` dependency. The OAuth callback chain has the
    OAuth provider redirecting the user's browser to the frontend, which
    forwards code+state to us. The state token (HMAC over org_id +
    agent_id) is the principal — we trust nothing in headers here.

    Frontend should still be the only origin allowed via CORS; that plus
    state-token signature is the auth.
    """
    from app.oauth.base import NATIVE_HANDLERS as _H, decode_state

    try:
        payload = decode_state(body.state)
    except NativeOAuthError as e:
        log.warning("oauth callback: bad state — %s", e)
        raise HTTPException(400, str(e))

    provider = payload.get("p")
    if provider not in _H:
        raise HTTPException(400, f"state references unknown provider: {provider}")

    handler = get_handler(provider)
    org_id = UUID(payload["o"])
    async with session_for_org(org_id) as db:
        try:
            row = await handler.handle_callback(
                code=body.code, state=body.state, db=db
            )
            await db.commit()
        except NativeOAuthError as e:
            log.exception("oauth callback failed provider=%s", provider)
            raise HTTPException(502, f"oauth callback failed: {e}")
        return _row_to_json(row)


# ─────────────────────────────────────────────────────────────────────────────
# Arcade-managed OAuth — for everything outside the native top-5.
#
# Flow:
#   1. Frontend POSTs /connections/arcade/start?provider=… → returns
#      { auth_url, auth_id, status }
#   2. Frontend redirects window.location to auth_url
#   3. After Arcade's flow completes, frontend POSTs /connections/arcade/record
#      with the auth_id; we poll Arcade once for terminal status + provider
#      identity, then upsert the Connection.
# ─────────────────────────────────────────────────────────────────────────────


class ArcadeStartBody(BaseModel):
    # `provider` is the Arcade-side auth_provider id (e.g. "aki-gcal",
    # "github") or a built-in slug. We accept any string and let Arcade
    # validate.
    provider: str = Field(min_length=1, max_length=64)
    agent_id: UUID | None = None
    scopes: list[str] | None = None


@router.post("/arcade/start")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def arcade_start(
    request: Request,
    body: ArcadeStartBody,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    settings = get_settings()
    if not settings.arcade_api_key:
        raise HTTPException(503, "ARCADE_API_KEY not configured")
    if body.agent_id is not None:
        await _validate_agent(db, principal.organization_id, body.agent_id)

    user_id = (
        str(principal.organization_id)
        if body.agent_id is None
        else f"{principal.organization_id}:{body.agent_id}"
    )
    ac = get_arcade_client()
    try:
        resp = await ac.start_auth(
            user_id=user_id,
            provider_id=body.provider,
            scopes=body.scopes,
            next_uri=f"{settings.web_base_url.rstrip('/')}/connect?arcade=ok",
        )
    except ArcadeError as e:
        log.exception("arcade start_auth failed")
        raise HTTPException(502, f"upstream: {e}")

    return {
        "auth_id": resp.get("id"),
        "auth_url": resp.get("url"),
        "status": resp.get("status"),
        "user_id": user_id,
        "agent_id": str(body.agent_id) if body.agent_id else None,
    }


@router.get("/arcade/status")
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def arcade_status(
    request: Request,
    auth_id: str = Query(..., min_length=1),
    wait: int = Query(0, ge=0, le=59),
    principal: Principal = Depends(get_principal),
) -> dict:
    if not get_settings().arcade_api_key:
        raise HTTPException(503, "ARCADE_API_KEY not configured")
    ac = get_arcade_client()
    try:
        return await ac.poll_auth_status(auth_id, wait_seconds=wait)
    except ArcadeError as e:
        log.exception("arcade poll_auth_status failed")
        raise HTTPException(502, f"upstream: {e}")


class ArcadeRecordBody(BaseModel):
    auth_id: str = Field(min_length=1)
    agent_id: UUID | None = None

    @field_validator("auth_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


@router.post("/arcade/record", status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def arcade_record(
    request: Request,
    body: ArcadeRecordBody,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Record a completed Arcade auth as a Connection row. We re-fetch
    the status server-side instead of trusting the frontend — defense in
    depth against a malicious POST."""
    settings = get_settings()
    if not settings.arcade_api_key:
        raise HTTPException(503, "ARCADE_API_KEY not configured")
    if body.agent_id is not None:
        await _validate_agent(db, principal.organization_id, body.agent_id)

    ac = get_arcade_client()
    try:
        status_resp = await ac.poll_auth_status(body.auth_id, wait_seconds=0)
    except ArcadeError as e:
        log.exception("arcade record: status fetch failed")
        raise HTTPException(502, f"upstream: {e}")

    if status_resp.get("status") != "completed":
        raise HTTPException(409, f"auth flow not completed: {status_resp.get('status')}")

    expected_user_id = (
        str(principal.organization_id)
        if body.agent_id is None
        else f"{principal.organization_id}:{body.agent_id}"
    )
    if status_resp.get("user_id") != expected_user_id:
        raise HTTPException(403, "auth flow user_id does not match principal scope")

    provider_id = status_resp.get("provider_id") or "arcade"
    row = Connection(
        id=uuid4(),
        organization_id=principal.organization_id,
        agent_id=body.agent_id,
        provider=provider_id,
        external_account_id=status_resp.get("id"),
        scopes=status_resp.get("scopes") or [],
        config={
            "source": "arcade",
            "auth_id": status_resp.get("id"),
            "provider_id": provider_id,
            "arcade_user_id": expected_user_id,
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
