"""Department CRUD + membership management.

RBAC summary:
  - GET    /v1/departments              → any authenticated user (filtered by role)
  - POST   /v1/departments              → owner / admin only
  - POST   /v1/departments/{id}/members → department admin+ only
  - DELETE /v1/departments/{id}         → owner only
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Department, Membership, User
from app.rbac import (
    Permission,
    assert_department_access,
    require_permission,
)

router = APIRouter(prefix="/v1/departments", tags=["departments"])

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]?$")


class DepartmentOut(BaseModel):
    id: UUID
    name: str
    slug: str
    hermes_model_name: str | None
    hermes_idle_minutes: int
    created_at: datetime


class CreateDepartmentBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64)
    hermes_model_name: str | None = Field(default=None, max_length=128)
    hermes_idle_minutes: int = Field(default=15, ge=1, le=24 * 60)
    slack_channel: str | None = Field(
        default=None, max_length=128, description="e.g. '#sales-bots'"
    )


class AddMemberBody(BaseModel):
    clerk_user_id: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="member", pattern="^(owner|member|viewer)$")


@router.get("", response_model=list[DepartmentOut])
async def list_departments(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[DepartmentOut]:
    q = (
        select(Department)
        .where(Department.organization_id == principal.organization_id)
        .order_by(Department.created_at.asc())
    )
    # Non-admins only see departments they belong to.
    if not principal.is_org_admin:
        if principal.department_ids:
            q = q.where(Department.id.in_(principal.department_ids))
        else:
            return []

    rows = (await db.execute(q)).scalars().all()
    return [
        DepartmentOut(
            id=r.id,
            name=r.name,
            slug=r.slug,
            hermes_model_name=r.hermes_model_name,
            hermes_idle_minutes=r.hermes_idle_minutes,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("", response_model=DepartmentOut, status_code=201)
async def create_department(
    body: CreateDepartmentBody,
    principal: Principal = Depends(require_permission(Permission.DEPARTMENT_CREATE)),
    db: AsyncSession = Depends(get_session),
) -> DepartmentOut:
    if not _SLUG_OK.match(body.slug):
        raise HTTPException(400, "slug must be kebab-case alphanumeric")

    row = Department(
        id=uuid4(),
        organization_id=principal.organization_id,
        name=body.name,
        slug=body.slug,
        hermes_model_name=body.hermes_model_name,
        hermes_idle_minutes=body.hermes_idle_minutes,
        notification_config=({"slack_channel": body.slack_channel} if body.slack_channel else {}),
    )
    db.add(row)
    try:
        await db.flush()
    except Exception as e:
        raise HTTPException(409, "department slug already exists in this org") from e

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="department.create",
        target=str(row.id),
        payload={"name": body.name, "slug": body.slug},
    )
    await db.commit()
    return DepartmentOut(
        id=row.id,
        name=row.name,
        slug=row.slug,
        hermes_model_name=row.hermes_model_name,
        hermes_idle_minutes=row.hermes_idle_minutes,
        created_at=row.created_at,
    )


@router.post("/{dept_id}/members", status_code=201)
async def add_member(
    dept_id: UUID,
    body: AddMemberBody,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    # Verify dept belongs to the principal's org.
    dept = (
        await db.execute(
            select(Department).where(
                Department.id == dept_id,
                Department.organization_id == principal.organization_id,
            )
        )
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(404, "department not found")

    # RBAC: admin+ in this department.
    await assert_department_access(principal, dept_id, min_role="admin")

    # Resolve the user being added; must belong to the same org.
    user = (
        await db.execute(select(User).where(User.clerk_user_id == body.clerk_user_id))
    ).scalar_one_or_none()
    if user is None or user.organization_id != principal.organization_id:
        raise HTTPException(404, "user not found in this organization")

    # Idempotent: skip if (user, dept) row already exists.
    existing = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.department_id == dept_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(Membership(user_id=user.id, department_id=dept_id, role=body.role))
        await append_audit(
            db,
            principal.organization_id,
            actor=principal.user_id,
            action="department.add_member",
            target=str(dept_id),
            payload={"user_id": str(user.id), "role": body.role},
        )
        await db.commit()
    return {"department_id": str(dept_id), "user_id": str(user.id), "role": body.role}


@router.delete("/{dept_id}", status_code=204)
async def delete_department(
    dept_id: UUID,
    principal: Principal = Depends(require_permission(Permission.ADMIN_FULL)),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a department and all its associated data.

    Requires owner or admin role. Memberships and connections cascade.
    """
    dept = (
        await db.execute(
            select(Department).where(
                Department.id == dept_id,
                Department.organization_id == principal.organization_id,
            )
        )
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(404, "department not found")

    await db.delete(dept)
    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="department.delete",
        target=str(dept_id),
        payload={"name": dept.name, "slug": dept.slug},
    )
    await db.commit()
