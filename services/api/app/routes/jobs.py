"""Jobs HTTP surface.

Endpoints:
  POST   /v1/jobs                  — create + enqueue (member+)
  GET    /v1/jobs                  — list (filterable by dept + status)
  GET    /v1/jobs/{id}             — single row
  GET    /v1/jobs/{id}/events      — SSE feed of job_events (live + history)
  POST   /v1/jobs/{id}/cancel      — mark cancelled (creator or admin+)

RBAC:
  - create → job:create + department membership
  - list   → job:read (filtered to accessible departments)
  - get    → job:read
  - cancel → job:cancel OR be the job creator
  - events → job:read

A job submission carries an optional `department_slug`; if omitted we fall
back to the same resolution chain as chat (`X-Hermes-Department` header,
primary membership, org default).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import Principal
from app.cost_caps import enforce_spend_cap
from app.middleware import get_principal, get_session
from app.models import Department, Job, JobEvent
from app.rbac import (
    Permission,
    assert_department_access,
    principal_has_permission,
    require_permission,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


class CreateJobBody(BaseModel):
    brief: str = Field(..., min_length=1, max_length=64_000)
    department_slug: str | None = Field(default=None, max_length=64)
    schedule_cron: str | None = Field(default=None, max_length=128)
    deadline_at: datetime | None = None


class JobOut(BaseModel):
    id: UUID
    department_id: UUID
    actor: str
    brief: str
    status: str
    schedule_cron: str | None
    next_run_at: datetime | None
    deadline_at: datetime | None
    result_summary: str | None
    cost_usd: float
    brain_source_id: UUID | None
    created_at: datetime
    updated_at: datetime


def _to_out(row: Job) -> JobOut:
    return JobOut(
        id=row.id,
        department_id=row.department_id,
        actor=row.actor,
        brief=row.brief,
        status=row.status,
        schedule_cron=row.schedule_cron,
        next_run_at=row.next_run_at,
        deadline_at=row.deadline_at,
        result_summary=row.result_summary,
        cost_usd=float(row.cost_usd or 0),
        brain_source_id=row.brain_source_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _resolve_dept(
    request: Request, principal: Principal, db: AsyncSession,
    explicit_slug: str | None,
) -> UUID:
    """Same chain as chat.py::_resolve_department_id, with explicit body slug."""
    slug = explicit_slug or request.headers.get("X-Hermes-Department")
    if slug:
        row = (
            await db.execute(
                select(Department.id).where(
                    Department.organization_id == principal.organization_id,
                    Department.slug == slug,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, f"department slug not found: {slug}")
        return row
    if principal.department_ids:
        return principal.department_ids[0]
    fallback = (
        await db.execute(
            select(Department.id).where(
                Department.organization_id == principal.organization_id,
                Department.slug == "default",
            )
        )
    ).scalar_one_or_none()
    if fallback is None:
        raise HTTPException(404, "no department for this user")
    return fallback


@router.post("", response_model=JobOut, status_code=201)
async def create_job(
    body: CreateJobBody,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOB_CREATE)),
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    dept_id = await _resolve_dept(request, principal, db, body.department_slug)
    await assert_department_access(principal, dept_id, min_permission=Permission.JOB_CREATE)

    # Enforce spend cap before expensive LLM job
    await enforce_spend_cap(db, principal.organization_id, estimated_cost=0.10)

    is_scheduled = body.schedule_cron is not None
    status = "queued" if not is_scheduled else "waiting_human"  # waits for cron
    next_run_at = None
    if is_scheduled:
        from app.scheduler import _next_fire
        from datetime import timezone
        next_run_at = _next_fire(body.schedule_cron, datetime.now(timezone.utc))

    job = Job(
        id=uuid4(),
        organization_id=principal.organization_id,
        department_id=dept_id,
        actor=principal.user_id,
        brief=body.brief,
        status=status,
        schedule_cron=body.schedule_cron,
        next_run_at=next_run_at,
        deadline_at=body.deadline_at,
    )
    db.add(job)
    await db.flush()

    db.add(JobEvent(job_id=job.id, kind="status_change",
                    payload={"to": status, "scheduled": is_scheduled}))
    await append_audit(
        db, principal.organization_id, actor=principal.user_id,
        action="job.create", target=str(job.id),
        payload={"department_id": str(dept_id), "scheduled": is_scheduled,
                 "cron": body.schedule_cron},
    )
    await db.commit()

    if not is_scheduled:
        # Fire-and-forget enqueue. arq doesn't return synchronously.
        from app.worker import enqueue_job
        try:
            await enqueue_job(job.id, principal.organization_id)
        except Exception:
            # If Redis is down, the job stays queued and the next scheduler
            # tick will sweep it (cron path). Don't fail the API call.
            log.exception("enqueue failed for job %s; row stays queued", job.id)

    return _to_out(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    department_slug: str | None = Query(None, max_length=64),
    status: Literal["queued", "running", "waiting_human", "done", "failed",
                    "cancelled"] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_permission(Permission.JOB_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[JobOut]:
    q = select(Job).where(Job.organization_id == principal.organization_id)
    if department_slug:
        sub = select(Department.id).where(
            Department.organization_id == principal.organization_id,
            Department.slug == department_slug,
        )
        q = q.where(Job.department_id.in_(sub))
    # Non-admins only see jobs in departments they belong to.
    if not principal.is_org_admin and principal.department_ids:
        q = q.where(Job.department_id.in_(principal.department_ids))
    elif not principal.is_org_admin:
        return []
    if status:
        q = q.where(Job.status == status)
    q = q.order_by(Job.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: UUID,
    principal: Principal = Depends(require_permission(Permission.JOB_READ)),
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    row = (
        await db.execute(select(Job).where(Job.id == job_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "job not found")
    # Non-admins can only read jobs in their departments.
    if not principal.is_org_admin and row.department_id not in principal.department_ids:
        raise HTTPException(404, "job not found")
    return _to_out(row)


@router.post("/{job_id}/cancel", status_code=204)
async def cancel_job(
    job_id: UUID,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    row = (
        await db.execute(select(Job).where(Job.id == job_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "job not found")
    # Non-admins can only cancel jobs in their departments.
    if not principal.is_org_admin and row.department_id not in principal.department_ids:
        raise HTTPException(404, "job not found")

    # RBAC: admin+ can cancel any job; regular members can only cancel their own.
    if not principal_has_permission(principal, Permission.JOB_CANCEL):
        if row.actor != principal.user_id:
            raise HTTPException(403, "only the job creator or an admin can cancel")

    if row.status in ("done", "cancelled"):
        return
    # Mark cancelled; the running worker checks status periodically and
    # bails if cancelled. For v1 we don't kill the running Hermes turn.
    await db.execute(
        text("update jobs set status='cancelled', updated_at=now() where id=:id"),
        {"id": str(job_id)},
    )
    db.add(JobEvent(job_id=job_id, kind="status_change",
                    payload={"to": "cancelled", "by": principal.user_id}))
    await append_audit(
        db, principal.organization_id, actor=principal.user_id,
        action="job.cancel", target=str(job_id), payload={},
    )
    await db.commit()


@router.get("/{job_id}/events")
async def stream_events(
    job_id: UUID,
    principal: Principal = Depends(require_permission(Permission.JOB_READ)),
    db: AsyncSession = Depends(get_session),
):
    """Server-Sent Events feed for live job_events.

    Sends a synthetic `event: history` block with the latest 200 rows up
    front, then long-polls every 2s for new rows. Closes when status
    transitions to done/failed/cancelled.
    """
    row = (
        await db.execute(select(Job).where(Job.id == job_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "job not found")
    # Non-admins can only stream events for jobs in their departments.
    if not principal.is_org_admin and row.department_id not in principal.department_ids:
        raise HTTPException(404, "job not found")

    org_id = principal.organization_id

    async def gen():
        from app.db import session_for_org

        # 1) Initial history snapshot.
        async with session_for_org(org_id) as s:
            hist = (
                await s.execute(
                    select(JobEvent).where(JobEvent.job_id == job_id)
                    .order_by(JobEvent.ts.desc()).limit(200)
                )
            ).scalars().all()
        last_id = hist[0].id if hist else 0
        # Send oldest first so UI can append in order.
        for ev in reversed(hist):
            yield _sse(ev)

        # 2) Poll for new rows. Stop when job is terminal.
        while True:
            await asyncio.sleep(2)
            async with session_for_org(org_id) as s:
                new = (
                    await s.execute(
                        select(JobEvent).where(
                            JobEvent.job_id == job_id, JobEvent.id > last_id
                        ).order_by(JobEvent.id.asc())
                    )
                ).scalars().all()
                for ev in new:
                    yield _sse(ev)
                    last_id = ev.id
                job_status = (
                    await s.execute(select(Job.status).where(Job.id == job_id))
                ).scalar_one_or_none()
            if job_status in ("done", "failed", "cancelled"):
                yield f"event: end\ndata: {json.dumps({'status': job_status})}\n\n"
                return

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _sse(ev: JobEvent) -> str:
    payload = {"id": ev.id, "kind": ev.kind, "ts": ev.ts.isoformat(),
               "payload": ev.payload}
    return f"event: {ev.kind}\ndata: {json.dumps(payload)}\n\n"
