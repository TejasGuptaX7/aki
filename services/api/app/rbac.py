"""Role-Based Access Control (RBAC) engine for Aki.

Permissions are granular strings (e.g. ``chat:create``). Roles are coarse
buckets (owner, admin, member, viewer) that map to sets of permissions.

FastAPI integration
-------------------
Use ``require_permission(Permission.CHAT_CREATE)`` as a route dependency::

    @router.post("/chat")
    async def chat(
        principal: Principal = Depends(require_permission(Permission.CHAT_CREATE)),
    ):
        ...

Department-scoped checks
------------------------
For actions that target a specific department, resolve the department first,
then call ``assert_department_access``::

    dept_id = await _resolve_department(...)
    await assert_department_access(principal, dept_id, min_role="member")

Caching
-------
``Principal`` caches the user's highest role and a per-department role map so
that RBAC checks are O(1) and require no extra DB round-trips after auth.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.auth import Principal
from app.middleware import get_principal


class Permission(StrEnum):
    """Granular action tokens."""

    CHAT_CREATE = "chat:create"
    CHAT_READ = "chat:read"
    JOB_CREATE = "job:create"
    JOB_READ = "job:read"
    JOB_CANCEL = "job:cancel"
    DEPARTMENT_CREATE = "department:create"
    DEPARTMENT_UPDATE = "department:update"
    DEPARTMENT_DELETE = "department:delete"
    DEPARTMENT_MANAGE_MEMBERS = "department:manage_members"
    CONNECTION_CREATE = "connection:create"
    CONNECTION_DELETE = "connection:delete"
    CONNECTION_READ = "connection:read"
    BRAIN_INGEST = "brain:ingest"
    BRAIN_RETRIEVE = "brain:retrieve"
    BRAIN_EXPORT = "brain:export"
    AUDIT_READ = "audit:read"
    DEVICE_READ = "device:read"
    DEVICE_REVOKE = "device:revoke"
    BILLING_READ = "billing:read"
    BILLING_MANAGE = "billing:manage"
    ADMIN_FULL = "admin:full"


_ALL_PERMISSIONS = list(Permission)

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "owner": set(_ALL_PERMISSIONS),
    "admin": {
        p for p in _ALL_PERMISSIONS if p not in (Permission.BILLING_MANAGE, Permission.ADMIN_FULL)
    },
    "member": {
        Permission.CHAT_CREATE,
        Permission.CHAT_READ,
        Permission.JOB_CREATE,
        Permission.JOB_READ,
        Permission.BRAIN_RETRIEVE,
        Permission.DEVICE_READ,
        Permission.CONNECTION_READ,
        Permission.AUDIT_READ,
    },
    "viewer": {
        Permission.CHAT_READ,
        Permission.JOB_READ,
        Permission.BRAIN_RETRIEVE,
        Permission.AUDIT_READ,
    },
}

ROLE_RANK: dict[str, int] = {
    "owner": 4,
    "admin": 3,
    "member": 2,
    "viewer": 1,
}


def principal_has_permission(principal: Principal, permission: Permission) -> bool:
    """Check whether the principal's *highest* role grants ``permission``.

    This is the right check for org-level actions (create a department,
    manage billing, etc.).
    """
    return permission in ROLE_PERMISSIONS.get(principal.role, set())


def principal_has_dept_permission(
    principal: Principal, dept_id: UUID, permission: Permission
) -> bool:
    """Check whether the principal's role *inside a specific department*
    grants ``permission``.
    """
    role = principal.department_roles.get(dept_id, "viewer")
    return permission in ROLE_PERMISSIONS.get(role, set())


def principal_role_at_least(principal: Principal, dept_id: UUID, min_role: str) -> bool:
    """Return ``True`` if the principal's role in ``dept_id`` is at least
    ``min_role`` in the hierarchy (viewer < member < admin < owner)."""
    actual = ROLE_RANK.get(principal.department_roles.get(dept_id, "viewer"), 0)
    required = ROLE_RANK.get(min_role, 0)
    return actual >= required


def require_permission(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    """FastAPI dependency factory.

    Returns a dependency that raises 403 if the principal does not hold
    ``permission`` via their highest role.
    """

    async def _checker(
        principal: Principal = Depends(get_principal),  # noqa: B008  (FastAPI Depends idiom)
    ) -> Principal:
        if not principal_has_permission(principal, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: {permission.value}",
            )
        return principal

    return _checker


async def assert_department_access(
    principal: Principal,
    dept_id: UUID,
    *,
    min_permission: Permission | None = None,
    min_role: str | None = None,
) -> None:
    """Raise ``HTTPException(403)`` if the principal lacks access to
    ``dept_id``.

    At least one of ``min_permission`` or ``min_role`` must be supplied.
    """
    if min_role is not None and not principal_role_at_least(principal, dept_id, min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"requires {min_role} role in this department",
        )
    if min_permission is not None and not principal_has_dept_permission(
        principal, dept_id, min_permission
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"missing permission in this department: {min_permission.value}",
        )
