"""/notifications — ambient inbox for things the agent wants to surface async.

When an agent finishes a long task, hits a wall, or has a question that's
not blocking on an approval, it calls the `notify_user(title, body)` MCP
tool which inserts a row here. The frontend polls (or, later, gets pushed
via SSE / Slack / email) — this router is the read side.

Routes:
  GET  /notifications?dismissed=false   → list
  POST /notifications/{id}/dismiss      → mark dismissed_at = now()

Notifications are per-org; cross-agent (a notification from any agent in
the org shows up in the same inbox).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Notification


log = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_wire(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "agent_id": str(n.agent_id) if n.agent_id else None,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "payload": dict(n.payload) if isinstance(n.payload, dict) else {},
        "dismissed_at": (
            n.dismissed_at.isoformat() if n.dismissed_at else None
        ),
        "created_at": n.created_at.isoformat(),
    }


@router.get("")
async def list_notifications(
    dismissed: bool | None = Query(
        False,
        description=(
            "false (default) → undismissed only; true → dismissed only; "
            "omit / null → both"
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    q = select(Notification).where(
        Notification.organization_id == principal.organization_id
    )
    if dismissed is True:
        q = q.where(Notification.dismissed_at.is_not(None))
    elif dismissed is False:
        q = q.where(Notification.dismissed_at.is_(None))
    # dismissed is None → no filter (both)
    q = q.order_by(Notification.created_at.desc()).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    return [_to_wire(n) for n in rows]


@router.post("/{notification_id}/dismiss")
async def dismiss_notification(
    notification_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Set dismissed_at = now. Idempotent: dismissing an already-dismissed
    row is a no-op (returns the same dismissed_at)."""
    row = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == principal.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    if row.dismissed_at is None:
        row.dismissed_at = datetime.now(timezone.utc)
        await append_audit(
            db,
            principal.organization_id,
            actor=principal.user_id,
            action="notification.dismiss",
            target=str(row.id),
            payload={"kind": row.kind},
            agent_id=row.agent_id,
        )
        await db.commit()
        await db.refresh(row)
    return _to_wire(row)
