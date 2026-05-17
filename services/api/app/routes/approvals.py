"""/approvals — the tier-2 consent inbox.

Anything the agent classifies as tier-2 (see app/consent.py) lands here as a
pending row. A user approves or denies; the agent (when wired in a later
session) long-polls /wait or listens via the upcoming Slack interface.

Response shape (matches the frontend contract in apps/web/src/lib/api.ts:
`Approval` type):

  {
    id:         uuid str
    agent_id:   uuid str
    kind:       short label, e.g. "email.send", "account.create"
                (stored in DB as `action` — `kind` is the wire name)
    summary:    human-readable one-liner ("Send email to john@acme.com about contract")
    payload:    {tool: str, args: dict}    — the full tool-call details
    created_at: ISO timestamp
  }

The `wait` endpoint is for the agent runtime — long-polls up to N seconds
for a status change, returns immediately when status flips. v1 polls with
0.5s sleeps; a future Postgres LISTEN/NOTIFY upgrade is straightforward.

Approvals expire at `expires_at` (default +10 min from creation). A
GET past expiry returns the row with `status: "expired"` and the wait
endpoint resolves with the same.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Agent, Approval


log = logging.getLogger(__name__)
router = APIRouter(prefix="/approvals", tags=["approvals"])


# Long-poll cap. 60s is the right ceiling for HTTP — cloud LBs commonly
# cut idle connections at 60s.
WAIT_MAX_S = 60
WAIT_POLL_INTERVAL_S = 0.5

# How long an approval stays pending before auto-expiring. Mirrors the
# DB-side server_default; set explicitly here because SQLAlchemy ORM
# sends NULL when a `Mapped[datetime]` field isn't provided, and the
# column is NOT NULL.
DEFAULT_APPROVAL_TTL = timedelta(minutes=10)


def _effective_status(a: Approval, now: datetime) -> str:
    """Return the displayed status, accounting for expiry. We don't mutate
    the row on read — a background task (future) sets status='expired';
    until then, this projection masks pending-but-stale rows as expired."""
    if a.status == "pending" and a.expires_at <= now:
        return "expired"
    return a.status


def _to_wire(a: Approval, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    payload = dict(a.args) if isinstance(a.args, dict) else {}
    # Mirror the frontend's expected shape exactly.
    return {
        "id": str(a.id),
        "agent_id": str(a.agent_id),
        "kind": a.action,
        "summary": a.reason,
        "payload": {
            "tool": a.tool,
            "args": payload,
        },
        "status": _effective_status(a, now),
        "created_at": a.created_at.isoformat(),
        "expires_at": a.expires_at.isoformat(),
        "responded_at": a.responded_at.isoformat() if a.responded_at else None,
        "responded_by": a.responded_by,
    }


# ── Pydantic schemas ────────────────────────────────────────────────────────


class ApprovalCreate(BaseModel):
    """Body for POST /approvals. Used by the agent runtime (later session)
    when an agent wants to perform a tier-2 action."""

    agent_id: UUID
    kind: str = Field(min_length=1, max_length=128)
    tool: str = Field(min_length=1, max_length=128)
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(default="", max_length=2_000)

    @field_validator("kind", "tool")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_approvals(
    status_filter: str = Query(
        "pending",
        alias="status",
        description="status to filter by; 'all' returns every row",
        pattern=r"^(pending|approved|denied|expired|all)$",
    ),
    agent_id: UUID | None = Query(
        None, description="optional filter to one agent"
    ),
    limit: int = Query(100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    q = select(Approval).where(Approval.organization_id == principal.organization_id)
    if agent_id is not None:
        q = q.where(Approval.agent_id == agent_id)
    if status_filter != "all":
        # 'expired' is a derived state — query by pending + expires_at < now.
        # All other statuses are stored as-is.
        if status_filter == "expired":
            q = q.where(
                Approval.status == "pending",
                Approval.expires_at <= datetime.now(timezone.utc),
            )
        elif status_filter == "pending":
            q = q.where(
                Approval.status == "pending",
                Approval.expires_at > datetime.now(timezone.utc),
            )
        else:
            q = q.where(Approval.status == status_filter)
    q = q.order_by(Approval.created_at.desc()).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    now = datetime.now(timezone.utc)
    return [_to_wire(a, now) for a in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_approval(
    body: ApprovalCreate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Create a pending approval. v1 trusts the principal; the agent
    integration (next session) will route through a service auth path that
    still scopes by org via the same JWT mechanism."""
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == body.agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    row = Approval(
        id=uuid4(),
        organization_id=principal.organization_id,
        agent_id=body.agent_id,
        action=body.kind,
        tool=body.tool,
        args=body.args,
        reason=body.summary,
        status="pending",
        expires_at=datetime.now(timezone.utc) + DEFAULT_APPROVAL_TTL,
    )
    db.add(row)
    await db.flush()

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="approval.create",
        target=str(row.id),
        payload={"kind": body.kind, "tool": body.tool},
        agent_id=body.agent_id,
    )
    await db.commit()
    await db.refresh(row)
    return _to_wire(row)


async def _respond(
    db: AsyncSession,
    principal: Principal,
    approval_id: UUID,
    new_status: str,
) -> dict:
    """Shared body for /approve and /deny."""
    row = await db.scalar(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.organization_id == principal.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")

    now = datetime.now(timezone.utc)
    if row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"approval already {row.status}",
        )
    if row.expires_at <= now:
        # Expired-pending: don't let the user resurrect a stale request,
        # the agent has long since timed out waiting.
        raise HTTPException(
            status.HTTP_410_GONE,
            "approval expired; agent already timed out",
        )

    row.status = new_status
    row.responded_at = now
    row.responded_by = principal.user_id

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action=f"approval.{new_status}",
        target=str(row.id),
        payload={"kind": row.action, "tool": row.tool},
        agent_id=row.agent_id,
    )
    await db.commit()
    await db.refresh(row)
    return _to_wire(row)


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await _respond(db, principal, approval_id, "approved")


@router.post("/{approval_id}/deny")
async def deny(
    approval_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await _respond(db, principal, approval_id, "denied")


@router.get("/{approval_id}/wait")
async def wait_for_status(
    approval_id: Annotated[UUID, Path()],
    timeout: float = Query(
        30.0, ge=1.0, le=WAIT_MAX_S,
        description="seconds to wait for a status change; clamped to WAIT_MAX_S",
    ),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Long-poll: return immediately if the approval is no longer pending,
    otherwise wait up to `timeout` seconds. Used by the agent runtime to
    block a tool call on the user's decision.

    v1 polls every WAIT_POLL_INTERVAL_S. A future upgrade replaces this with
    Postgres LISTEN/NOTIFY on `approval_status_changed` so resolution is
    sub-100ms instead of <=500ms.
    """
    # Quick exit: not pending or expired → return state immediately.
    row = await db.scalar(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.organization_id == principal.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    now = datetime.now(timezone.utc)
    if row.status != "pending" or row.expires_at <= now:
        return _to_wire(row, now)

    deadline = asyncio.get_running_loop().time() + min(timeout, WAIT_MAX_S)
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(WAIT_POLL_INTERVAL_S)
        # Re-read inside the same session; SQLAlchemy will requery on .refresh
        await db.refresh(row)
        now = datetime.now(timezone.utc)
        if row.status != "pending" or row.expires_at <= now:
            return _to_wire(row, now)

    # Hit the long-poll timeout — caller should retry.
    return _to_wire(row, now)
