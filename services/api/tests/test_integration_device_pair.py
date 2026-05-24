"""Device pair → JWT → revoke → 401 cycle.

Fully exercises the device JWT path without touching Redis or Postgres.
We monkeypatch the device lookup and generate a fresh Ed25519 keypair.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from app import auth as auth_mod
from app.config import get_settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


def _gen_ed25519_pem() -> str:
    """Generate a fresh Ed25519 private key, PEM-encoded, unencrypted."""
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def _make_token(device_id, org_id, signing_key, exp=None, **extra):
    """Encode a device JWT with standard claims."""
    payload = {
        "iss": auth_mod.DEVICE_JWT_ISSUER,
        "aud": auth_mod.DEVICE_JWT_AUDIENCE,
        "sub": str(device_id),
        "user_id": str(uuid4()),
        "org_id": str(org_id),
        "jti": "test-jti",
        "exp": exp or (datetime.now(tz=UTC) + timedelta(minutes=5)),
        **extra,
    }
    return jwt.encode(payload, signing_key, algorithm="EdDSA")


async def test_valid_device_jwt(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "device_jwt_signing_key", _gen_ed25519_pem())

    device_id = uuid4()
    user_clerk = "user_test123"
    org_id = uuid4()
    dept_ids = [uuid4(), uuid4()]
    dept_roles = {dept_ids[0]: "admin", dept_ids[1]: "member"}

    async def fake_lookup(did):
        assert did == device_id
        return (user_clerk, org_id, dept_ids, dept_roles, "admin")

    monkeypatch.setattr(auth_mod, "_lookup_user_and_orgs_for_device", fake_lookup)

    token = _make_token(device_id, org_id, settings.device_jwt_signing_key)
    principal = await auth_mod._verify_device_jwt(token)

    assert principal.user_id == user_clerk
    assert principal.organization_id == org_id
    assert principal.device_id == device_id
    assert principal.department_ids == dept_ids
    assert principal.department_roles == dept_roles
    assert principal.role == "admin"
    assert principal.is_org_admin is True


async def test_revoked_device_returns_401(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "device_jwt_signing_key", _gen_ed25519_pem())

    async def fake_lookup(_did):
        return None  # revoked or unknown

    monkeypatch.setattr(auth_mod, "_lookup_user_and_orgs_for_device", fake_lookup)

    token = _make_token(uuid4(), uuid4(), settings.device_jwt_signing_key)
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod._verify_device_jwt(token)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower() or "unknown" in exc_info.value.detail.lower()


async def test_expired_device_jwt_returns_401(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "device_jwt_signing_key", _gen_ed25519_pem())

    async def fake_lookup(_did):
        return ("user_test", uuid4(), [], {}, "viewer")

    monkeypatch.setattr(auth_mod, "_lookup_user_and_orgs_for_device", fake_lookup)

    token = _make_token(
        uuid4(),
        uuid4(),
        settings.device_jwt_signing_key,
        exp=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod._verify_device_jwt(token)
    assert exc_info.value.status_code == 401
