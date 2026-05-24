"""Admin route authorization integration.

Tests that admin endpoints require proper permissions using a minimal
FastAPI app so we don't need the full lifespan/startup.
"""

from __future__ import annotations

from uuid import uuid4

from app.auth import Principal
from app.middleware import get_principal
from app.rbac import Permission, require_permission
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _client_for(principal: Principal):
    """Build a minimal FastAPI app with the principal injected via override."""
    app = FastAPI()

    async def override_get_principal():
        return principal

    app.dependency_overrides[get_principal] = override_get_principal

    @app.get("/admin/org")
    async def admin_org(p: Principal = Depends(require_permission(Permission.ADMIN_FULL))):
        return {"org_id": str(p.organization_id)}

    @app.get("/admin/users")
    async def admin_users(p: Principal = Depends(require_permission(Permission.ADMIN_FULL))):
        return {"users": []}

    @app.get("/billing/read")
    async def billing_read(p: Principal = Depends(require_permission(Permission.BILLING_READ))):
        return {"ok": True}

    return TestClient(app)


def test_admin_full_allows_owner():
    principal = Principal(
        user_id="user_owner",
        organization_id=uuid4(),
        department_ids=[uuid4()],
        role="owner",
        is_org_admin=True,
    )
    client = _client_for(principal)
    response = client.get("/admin/org")
    assert response.status_code == 200
    assert "org_id" in response.json()


def test_admin_full_blocks_admin():
    """Admins do NOT hold ADMIN_FULL (only owners do)."""
    principal = Principal(
        user_id="user_admin",
        organization_id=uuid4(),
        department_ids=[uuid4()],
        role="admin",
        is_org_admin=True,
    )
    client = _client_for(principal)
    response = client.get("/admin/org")
    assert response.status_code == 403
    assert "admin:full" in response.json()["detail"]


def test_admin_full_blocks_member():
    principal = Principal(
        user_id="user_member",
        organization_id=uuid4(),
        department_ids=[uuid4()],
        role="member",
        is_org_admin=False,
    )
    client = _client_for(principal)
    response = client.get("/admin/org")
    assert response.status_code == 403
    assert "admin:full" in response.json()["detail"]


def test_admin_full_blocks_viewer():
    principal = Principal(
        user_id="user_viewer",
        organization_id=uuid4(),
        department_ids=[uuid4()],
        role="viewer",
        is_org_admin=False,
    )
    client = _client_for(principal)
    response = client.get("/admin/users")
    assert response.status_code == 403


def test_billing_read_allows_admin():
    """Admins can read billing (a weaker permission than ADMIN_FULL)."""
    principal = Principal(
        user_id="user_admin",
        organization_id=uuid4(),
        department_ids=[uuid4()],
        role="admin",
        is_org_admin=True,
    )
    client = _client_for(principal)
    response = client.get("/billing/read")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_billing_read_blocks_viewer():
    principal = Principal(
        user_id="user_viewer",
        organization_id=uuid4(),
        department_ids=[uuid4()],
        role="viewer",
        is_org_admin=False,
    )
    client = _client_for(principal)
    response = client.get("/billing/read")
    assert response.status_code == 403
    assert "billing:read" in response.json()["detail"]
