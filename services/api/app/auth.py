"""Clerk JWT verification + Aki device JWT verification.

Three auth paths:
  1. Dev bypass: `X-Dev-Org-Id` header (gated by APP_ENV=dev AND
     ALLOW_DEV_AUTH_BYPASS=true).
  2. Clerk JWT (RS256, JWKS-verified). Falls back to a DB lookup on
     `clerk_user_id` if the JWT lacks the `org_id` claim.
  3. Aki device JWT (Ed25519, issued by this API). Used by paired desktop
     clients. Issuer is our own API base URL; same Principal shape, no
     callers change.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import select, text

from app.config import get_settings

settings = get_settings()
_jwks_cache: dict | None = None

# Issuer string for device JWTs. Must match what devices.py mints.
DEVICE_JWT_ISSUER = "aki-api"
DEVICE_JWT_AUDIENCE = "aki-device"


async def _lookup_org_by_clerk_user_id(clerk_user_id: str) -> UUID | None:
    """Fallback when the JWT has no org_id claim. RLS-bypassed because
    we don't yet know which org context to scope to — that's what we're
    looking up. Our table owner role can disable row_security per-session."""
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        result = await session.execute(
            select(User.organization_id).where(User.clerk_user_id == clerk_user_id)
        )
        return result.scalar_one_or_none()


async def _lookup_user_and_orgs_for_device(
    device_id: UUID,
) -> tuple[str, UUID, list[UUID]] | None:
    """For a device JWT, look up the (user_id, org_id, department_ids) tuple.
    RLS-bypassed for the same reason as the Clerk fallback above."""
    from app.db import SessionLocal
    from app.models import AkiDevice, Membership, User

    async with SessionLocal() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        row = (
            await session.execute(
                select(AkiDevice.user_id, AkiDevice.organization_id,
                       AkiDevice.revoked_at, User.clerk_user_id)
                .join(User, User.id == AkiDevice.user_id)
                .where(AkiDevice.id == device_id)
            )
        ).one_or_none()
        if row is None:
            return None
        user_id, org_id, revoked_at, clerk_user_id = row
        if revoked_at is not None:
            return None
        # Touch last_seen_at on every authenticated call. Best-effort.
        await session.execute(
            text(
                "update aki_devices set last_seen_at = now() where id = :id"
            ),
            {"id": str(device_id)},
        )
        await session.commit()
        dept_rows = (
            await session.execute(
                select(Membership.department_id).where(Membership.user_id == user_id)
            )
        ).scalars().all()
        return clerk_user_id, org_id, list(dept_rows)


async def _lookup_department_ids(user_id_or_clerk: str) -> list[UUID]:
    """Resolve a clerk_user_id (or app user_id) to the list of department_ids
    they're a member of. Returns [] if the user isn't found or has no
    memberships yet. RLS-bypassed."""
    from app.db import SessionLocal
    from app.models import Membership, User

    async with SessionLocal() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        # If we got a clerk user id, resolve to internal user_id first.
        user_row = (
            await session.execute(
                select(User.id).where(User.clerk_user_id == user_id_or_clerk)
            )
        ).scalar_one_or_none()
        if user_row is None:
            return []
        rows = (
            await session.execute(
                select(Membership.department_id).where(Membership.user_id == user_row)
            )
        ).scalars().all()
        return list(rows)


@dataclass(frozen=True)
class Principal:
    user_id: str                       # Clerk user id (e.g. "user_2abc…")
    organization_id: UUID              # resolved from users table
    department_ids: list[UUID] = field(default_factory=list)
    device_id: UUID | None = None      # set when authed via Aki device JWT


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None and settings.clerk_jwks_url:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(settings.clerk_jwks_url)
            r.raise_for_status()
            _jwks_cache = r.json()
    return _jwks_cache or {}


def _looks_like_device_jwt(token: str) -> bool:
    """Cheap unverified peek so we can route to the right verifier."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        return unverified.get("iss") == DEVICE_JWT_ISSUER
    except Exception:
        return False


async def _verify_device_jwt(token: str) -> Principal:
    if not settings.device_jwt_signing_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "device JWT verification is not configured",
        )
    try:
        claims = jwt.decode(
            token,
            settings.device_jwt_signing_key,
            algorithms=["EdDSA"],
            issuer=DEVICE_JWT_ISSUER,
            audience=DEVICE_JWT_AUDIENCE,
            options={"require": ["iss", "sub", "exp", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid device token: {e}")

    try:
        device_id = UUID(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device token: bad sub")

    looked_up = await _lookup_user_and_orgs_for_device(device_id)
    if looked_up is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device revoked or unknown")
    clerk_user_id, org_id, dept_ids = looked_up
    return Principal(
        user_id=clerk_user_id,
        organization_id=org_id,
        department_ids=dept_ids,
        device_id=device_id,
    )


async def verify(request: Request) -> Principal:
    # Dev bypass.
    if settings.app_env == "dev" and settings.allow_dev_auth_bypass:
        dev_org = request.headers.get("X-Dev-Org-Id")
        if dev_org:
            dev_user = request.headers.get("X-Dev-User-Id", "user_dev")
            dept_ids = await _lookup_department_ids(dev_user)
            return Principal(
                user_id=dev_user,
                organization_id=UUID(dev_org),
                department_ids=dept_ids,
            )

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth.removeprefix("Bearer ").strip()

    # Device-JWT path: when the unverified `iss` claim is ours, validate
    # Ed25519 against our own signing key.
    if _looks_like_device_jwt(token):
        return await _verify_device_jwt(token)

    # Clerk path.
    jwks = await _get_jwks()
    try:
        header = jwt.get_unverified_header(token)
        key = next(k for k in jwks.get("keys", []) if k["kid"] == header["kid"])
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.clerk_jwt_issuer,
            options={"require": ["iss", "sub", "exp"]},
        )
    except (StopIteration, jwt.PyJWTError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")

    org_id = claims.get("org_id")
    if not org_id:
        org_id = await _lookup_org_by_clerk_user_id(claims["sub"])
    if not org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no org for this user")

    clerk_sub = claims["sub"]
    dept_ids = await _lookup_department_ids(clerk_sub)
    return Principal(
        user_id=clerk_sub,
        organization_id=UUID(str(org_id)),
        department_ids=dept_ids,
    )
