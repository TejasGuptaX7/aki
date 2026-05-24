"""Round-trip a device JWT: sign with the configured key, then verify via
auth.verify's device-JWT branch.

This test fully exercises the JWT shape (claims, issuer, audience, EdDSA
signature) without touching Redis or Postgres. We monkeypatch the device
lookup to return a fixed (clerk_user_id, org_id, depts) tuple.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _gen_ed25519_pem() -> str:
    """Generate a fresh Ed25519 private key, PEM-encoded, unencrypted."""
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def test_device_jwt_round_trip(monkeypatch):
    from app import auth as auth_mod
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "device_jwt_signing_key", _gen_ed25519_pem())

    device_id = uuid4()
    user_clerk = "user_test123"
    org_id = uuid4()
    dept_ids = [uuid4(), uuid4()]

    async def fake_lookup(did):
        assert did == device_id
        dept_roles = {d: "admin" for d in dept_ids}
        return (user_clerk, org_id, dept_ids, dept_roles, "admin")

    monkeypatch.setattr(auth_mod, "_lookup_user_and_orgs_for_device", fake_lookup)

    token = jwt.encode(
        {
            "iss": auth_mod.DEVICE_JWT_ISSUER,
            "aud": auth_mod.DEVICE_JWT_AUDIENCE,
            "sub": str(device_id),
            "user_id": str(uuid4()),
            "org_id": str(org_id),
            "jti": "test-jti",
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=5),
        },
        settings.device_jwt_signing_key,
        algorithm="EdDSA",
    )

    principal = asyncio.run(auth_mod._verify_device_jwt(token))
    assert principal.user_id == user_clerk
    assert principal.organization_id == org_id
    assert principal.device_id == device_id
    assert principal.department_ids == dept_ids


def test_revoked_device_rejected(monkeypatch):
    from app import auth as auth_mod
    from app.config import get_settings
    from fastapi import HTTPException

    settings = get_settings()
    monkeypatch.setattr(settings, "device_jwt_signing_key", _gen_ed25519_pem())

    async def fake_lookup(_did):
        return None  # revoked or unknown

    monkeypatch.setattr(auth_mod, "_lookup_user_and_orgs_for_device", fake_lookup)

    token = jwt.encode(
        {
            "iss": auth_mod.DEVICE_JWT_ISSUER,
            "aud": auth_mod.DEVICE_JWT_AUDIENCE,
            "sub": str(uuid4()),
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=5),
        },
        settings.device_jwt_signing_key,
        algorithm="EdDSA",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_mod._verify_device_jwt(token))
    assert exc.value.status_code == 401
