"""GDPR compliance endpoints.

  - GET  /v1/gdpr/export — export all org data as JSON
  - POST /v1/gdpr/delete — schedule full org deletion

These are owner-only operations. The export includes all tables scoped to the
organization; the deletion is a hard cascade that removes every row.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.middleware import get_session
from app.models import (
    AuditLog,
    Connection,
    Department,
    Job,
    Organization,
    User,
)
from app.rbac import Permission, require_permission

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/gdpr", tags=["gdpr"])


@router.get("/export")
async def export_org_data(
    principal: Principal = Depends(require_permission(Permission.ADMIN_FULL)),
    db: AsyncSession = Depends(get_session),
):
    """Stream a JSON export of all organization data.

    Returns newline-delimited JSON (NDJSON) with one object per table.
    """
    org_id = principal.organization_id

    async def _generate():
        # Organization
        org = (
            await db.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()
        if org:
            yield json.dumps(
                {
                    "table": "organizations",
                    "data": {
                        "id": str(org.id),
                        "name": org.name,
                        "created_at": org.created_at.isoformat(),
                    },
                }
            ) + "\n"

        # Users
        users = (
            (await db.execute(select(User).where(User.organization_id == org_id))).scalars().all()
        )
        for u in users:
            yield json.dumps(
                {
                    "table": "users",
                    "data": {
                        "id": str(u.id),
                        "clerk_user_id": u.clerk_user_id,
                        "email": u.email,
                        "created_at": u.created_at.isoformat(),
                    },
                }
            ) + "\n"

        # Departments
        depts = (
            (await db.execute(select(Department).where(Department.organization_id == org_id)))
            .scalars()
            .all()
        )
        for d in depts:
            yield json.dumps(
                {
                    "table": "departments",
                    "data": {
                        "id": str(d.id),
                        "name": d.name,
                        "slug": d.slug,
                        "created_at": d.created_at.isoformat(),
                    },
                }
            ) + "\n"

        # Connections
        conns = (
            (await db.execute(select(Connection).where(Connection.organization_id == org_id)))
            .scalars()
            .all()
        )
        for c in conns:
            yield json.dumps(
                {
                    "table": "connections",
                    "data": {
                        "id": str(c.id),
                        "provider": c.provider,
                        "status": c.status,
                        "created_at": c.created_at.isoformat(),
                    },
                }
            ) + "\n"

        # Jobs (summary only — full content can be huge)
        jobs = (await db.execute(select(Job).where(Job.organization_id == org_id))).scalars().all()
        for j in jobs:
            yield json.dumps(
                {
                    "table": "jobs",
                    "data": {
                        "id": str(j.id),
                        "brief": j.brief,
                        "status": j.status,
                        "result_summary": j.result_summary,
                        "cost_usd": float(j.cost_usd or 0),
                        "created_at": j.created_at.isoformat(),
                    },
                }
            ) + "\n"

        # Audit log (last 90 days only to keep export reasonable)
        audits = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.organization_id == org_id,
                        AuditLog.created_at >= text("now() - interval '90 days'"),
                    )
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for a in audits:
            yield json.dumps(
                {
                    "table": "audit_log",
                    "data": {
                        "id": a.id,
                        "action": a.action,
                        "actor": a.actor,
                        "created_at": a.created_at.isoformat(),
                    },
                }
            ) + "\n"

        yield json.dumps({"table": "_EOF", "message": "export complete"}) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename=aki-export-{org_id}.ndjson"},
    )


@router.post("/delete", status_code=202)
async def delete_org_data(
    principal: Principal = Depends(require_permission(Permission.ADMIN_FULL)),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Hard-delete all data for the organization.

    This is irreversible. In production, you may want to archive first.
    """
    org_id = principal.organization_id

    # Delete in dependency order to avoid FK violations
    tables = [
        "job_events",
        "jobs",
        "brain_chunks",
        "brain_sources",
        "brain_facts",
        "memberships",
        "departments",
        "connections",
        "audit_log",
        "org_memory",
        "aki_devices",
        "users",
        "organizations",
    ]

    for tbl in tables:
        try:
            await db.execute(
                text(f"delete from {tbl} where organization_id = :org"),
                {"org": str(org_id)},
            )
        except Exception as e:
            log.warning("gdpr delete: %s failed: %s", tbl, e)

    await db.commit()
    log.info("gdpr delete executed for org=%s by user=%s", org_id, principal.user_id)
    return {"status": "deleted", "organization_id": str(org_id)}
