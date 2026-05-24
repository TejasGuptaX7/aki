"""GET /audit — paginated audit log for the principal's org.

RLS scopes this automatically to the org via the session GUC. The hash chain
fields are included so a client can verify the chain locally.

RBAC:
  - list → audit:read (all authenticated users)
  - append-only; no write endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.middleware import get_session
from app.models import AuditLog
from app.rbac import Permission, require_permission


router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(
    limit: int = Query(50, ge=1, le=200),
    after_id: int | None = Query(None, description="return rows with id > after_id (forward paging)"),
    before_id: int | None = Query(None, description="return rows with id < before_id (backward paging)"),
    principal: Principal = Depends(require_permission(Permission.AUDIT_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict:
    q = select(AuditLog).where(AuditLog.organization_id == principal.organization_id)
    if after_id is not None:
        q = q.where(AuditLog.id > after_id).order_by(AuditLog.id.asc())
    else:
        if before_id is not None:
            q = q.where(AuditLog.id < before_id)
        q = q.order_by(AuditLog.id.desc())
    q = q.limit(limit)

    rows = (await db.execute(q)).scalars().all()
    if after_id is not None:
        rows = list(reversed(rows))  # always return newest-first to caller

    return {
        "items": [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "target": r.target,
                "payload": r.payload,
                "content_hash": r.content_hash,
                "prev_hash": r.prev_hash,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "next_before_id": rows[-1].id if rows else None,
    }
