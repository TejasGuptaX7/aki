"""Admin console API endpoints.

Provides org-level management for owners and admins:
  - GET  /v1/admin/org          — org settings
  - PATCH /v1/admin/org         — update org settings
  - GET  /v1/admin/users        — list org users
  - GET  /v1/admin/usage        — aggregated usage dashboard
  - POST /v1/admin/spend-cap    — set hard/soft spending caps
  - GET  /v1/admin/audit-summary — high-level audit stats

All endpoints require admin:full or owner role.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.middleware import get_session
from app.models import AuditLog, Department, Membership, Organization, User
from app.rbac import Permission, require_permission

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin", tags=["admin"])


# ── Org settings ───────────────────────────────────────────────────────────


class OrgSettingsOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    hermes_model_name: str | None
    hermes_idle_minutes: int
    spend_cap_hard: float | None
    spend_cap_soft: float | None
    data_retention_days: int | None


class OrgSettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    hermes_model_name: str | None = Field(default=None, max_length=128)
    hermes_idle_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    spend_cap_hard: float | None = Field(default=None, ge=0)
    spend_cap_soft: float | None = Field(default=None, ge=0)
    data_retention_days: int | None = Field(default=None, ge=1, le=3650)


@router.get("/org", response_model=OrgSettingsOut)
async def get_org_settings(
    principal: Principal = Depends(require_permission(Permission.ADMIN_FULL)),
    db: AsyncSession = Depends(get_session),
) -> OrgSettingsOut:
    row = (
        await db.execute(select(Organization).where(Organization.id == principal.organization_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "organization not found")

    # Settings stored in JSONB for flexibility; fallback to defaults.
    cfg = row.settings or {} if hasattr(row, "settings") else {}
    return OrgSettingsOut(
        id=row.id,
        name=row.name,
        created_at=row.created_at,
        hermes_model_name=cfg.get("hermes_model_name"),
        hermes_idle_minutes=cfg.get("hermes_idle_minutes", 15),
        spend_cap_hard=cfg.get("spend_cap_hard"),
        spend_cap_soft=cfg.get("spend_cap_soft"),
        data_retention_days=cfg.get("data_retention_days"),
    )


@router.patch("/org", response_model=OrgSettingsOut)
async def patch_org_settings(
    body: OrgSettingsPatch,
    principal: Principal = Depends(require_permission(Permission.ADMIN_FULL)),
    db: AsyncSession = Depends(get_session),
) -> OrgSettingsOut:
    row = (
        await db.execute(select(Organization).where(Organization.id == principal.organization_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "organization not found")

    if body.name is not None:
        row.name = body.name

    # Merge settings into JSONB field (create if absent)
    cfg = dict(row.settings) if hasattr(row, "settings") and row.settings else {}
    if body.hermes_model_name is not None:
        cfg["hermes_model_name"] = body.hermes_model_name
    if body.hermes_idle_minutes is not None:
        cfg["hermes_idle_minutes"] = body.hermes_idle_minutes
    if body.spend_cap_hard is not None:
        cfg["spend_cap_hard"] = body.spend_cap_hard
    if body.spend_cap_soft is not None:
        cfg["spend_cap_soft"] = body.spend_cap_soft
    if body.data_retention_days is not None:
        cfg["data_retention_days"] = body.data_retention_days

    if hasattr(row, "settings"):
        row.settings = cfg

    await db.commit()
    return await get_org_settings(principal, db)


class SpendCapBody(BaseModel):
    spend_cap_hard: float | None = Field(default=None, ge=0)
    spend_cap_soft: float | None = Field(default=None, ge=0)


@router.post("/spend-cap", response_model=OrgSettingsOut)
async def set_spend_cap(
    body: SpendCapBody,
    principal: Principal = Depends(require_permission(Permission.BILLING_MANAGE)),
    db: AsyncSession = Depends(get_session),
) -> OrgSettingsOut:
    """Set hard and/or soft spending caps for the organization."""
    row = (
        await db.execute(select(Organization).where(Organization.id == principal.organization_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "organization not found")

    cfg = dict(row.settings) if row.settings else {}
    if body.spend_cap_hard is not None:
        cfg["spend_cap_hard"] = body.spend_cap_hard
    if body.spend_cap_soft is not None:
        cfg["spend_cap_soft"] = body.spend_cap_soft
    row.settings = cfg

    await db.commit()
    return await get_org_settings(principal, db)


# ── User management ────────────────────────────────────────────────────────


class UserOut(BaseModel):
    id: UUID
    clerk_user_id: str
    email: str | None
    created_at: datetime
    role: str  # highest role across departments


@router.get("/users", response_model=list[UserOut])
async def list_org_users(
    principal: Principal = Depends(require_permission(Permission.ADMIN_FULL)),
    db: AsyncSession = Depends(get_session),
) -> list[UserOut]:
    rows = (
        (
            await db.execute(
                select(User)
                .where(User.organization_id == principal.organization_id)
                .order_by(User.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    # Build a map of user_id -> highest role across departments.
    memberships = (
        (
            await db.execute(
                select(Membership).where(
                    Membership.department_id.in_(
                        select(Department.id).where(
                            Department.organization_id == principal.organization_id
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    user_roles: dict[UUID, str] = {}
    role_rank = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}
    for m in memberships:
        current_rank = role_rank.get(user_roles.get(m.user_id, "viewer"), 0)
        new_rank = role_rank.get(m.role, 0)
        if new_rank > current_rank:
            user_roles[m.user_id] = m.role

    return [
        UserOut(
            id=r.id,
            clerk_user_id=r.clerk_user_id,
            email=r.email,
            created_at=r.created_at,
            role=user_roles.get(r.id, "viewer"),
        )
        for r in rows
    ]


# ── Usage dashboard ────────────────────────────────────────────────────────


class UsageDashboard(BaseModel):
    total_cost_30d: float
    total_chats_30d: int
    total_jobs_30d: int
    total_tool_calls_30d: int
    daily: list[dict]
    top_departments: list[dict]


@router.get("/usage", response_model=UsageDashboard)
async def usage_dashboard(
    principal: Principal = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> UsageDashboard:
    window_start = datetime.now(UTC) - timedelta(days=30)
    org_id = principal.organization_id

    # Aggregate from audit_log (source of truth)
    agg = (
        (
            await db.execute(
                text("""
                select
                  coalesce(sum((payload->>'cost_usd')::numeric), 0) as cost,
                  sum(case when action = 'chat.complete' then 1 else 0 end) as chats,
                  sum(case when action = 'job.complete' then 1 else 0 end) as jobs,
                  sum(case when action = 'chat.tool_call' then 1 else 0 end) as tools
                from audit_log
                where organization_id = :org
                  and created_at >= :start
            """),
                {"org": str(org_id), "start": window_start},
            )
        )
        .mappings()
        .one()
    )

    daily = (
        (
            await db.execute(
                text("""
                select
                  date_trunc('day', created_at)::date as day,
                  coalesce(sum((payload->>'cost_usd')::numeric), 0) as cost,
                  sum(case when action = 'chat.complete' then 1 else 0 end) as chats,
                  sum(case when action = 'job.complete' then 1 else 0 end) as jobs
                from audit_log
                where organization_id = :org
                  and created_at >= :start
                group by 1
                order by 1 desc
            """),
                {"org": str(org_id), "start": window_start},
            )
        )
        .mappings()
        .all()
    )

    # Top departments by cost (from audit_log payload)
    top_depts = (
        (
            await db.execute(
                text("""
                select
                  coalesce(payload->>'department_id', 'unknown') as dept_id,
                  count(*) as events,
                  coalesce(sum((payload->>'cost_usd')::numeric), 0) as cost
                from audit_log
                where organization_id = :org
                  and created_at >= :start
                group by 1
                order by cost desc
                limit 5
            """),
                {"org": str(org_id), "start": window_start},
            )
        )
        .mappings()
        .all()
    )

    return UsageDashboard(
        total_cost_30d=float(agg["cost"] or 0),
        total_chats_30d=int(agg["chats"] or 0),
        total_jobs_30d=int(agg["jobs"] or 0),
        total_tool_calls_30d=int(agg["tools"] or 0),
        daily=[dict(r) for r in daily],
        top_departments=[dict(r) for r in top_depts],
    )


# ── Audit summary ──────────────────────────────────────────────────────────


class AuditSummary(BaseModel):
    total_events: int
    events_today: int
    events_this_week: int
    top_actions: list[dict]


@router.get("/audit-summary", response_model=AuditSummary)
async def audit_summary(
    principal: Principal = Depends(require_permission(Permission.AUDIT_READ)),
    db: AsyncSession = Depends(get_session),
) -> AuditSummary:
    org_id = principal.organization_id
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())

    total = (
        await db.execute(select(func.count(AuditLog.id)).where(AuditLog.organization_id == org_id))
    ).scalar_one()

    today_count = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.organization_id == org_id,
                AuditLog.created_at >= today,
            )
        )
    ).scalar_one()

    week_count = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.organization_id == org_id,
                AuditLog.created_at >= week_start,
            )
        )
    ).scalar_one()

    top_actions = (
        (
            await db.execute(
                text("""
                select action, count(*) as cnt
                from audit_log
                where organization_id = :org
                  and created_at >= :start
                group by action
                order by cnt desc
                limit 10
            """),
                {"org": str(org_id), "start": week_start},
            )
        )
        .mappings()
        .all()
    )

    return AuditSummary(
        total_events=int(total),
        events_today=int(today_count),
        events_this_week=int(week_count),
        top_actions=[dict(r) for r in top_actions],
    )
