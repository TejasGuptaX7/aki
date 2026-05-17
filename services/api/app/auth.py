"""Clerk JWT verification.

Stub: in dev, accepts a header `X-Dev-Org-Id` so the API works without Clerk
configured. In staging/prod, verifies RS256 against the Clerk JWKS.

If the verified JWT has no `org_id` claim (common when the Clerk JWT template
hasn't propagated, or the user signed in before metadata was set), we fall
back to a DB lookup on `clerk_user_id`. Requires bypassing RLS for that one
query — handled in `_lookup_org_by_clerk_user_id`.
"""
from dataclasses import dataclass
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import select, text

from app.config import get_settings

settings = get_settings()
_jwks_cache: dict | None = None


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


@dataclass(frozen=True)
class Principal:
    user_id: str          # Clerk user id (e.g. "user_2abc…")
    organization_id: UUID  # resolved from users table


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None and settings.clerk_jwks_url:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(settings.clerk_jwks_url)
            r.raise_for_status()
            _jwks_cache = r.json()
    return _jwks_cache or {}


async def verify(request: Request) -> Principal:
    # Dev bypass: explicit opt-in via BOTH app_env=dev AND
    # ALLOW_DEV_AUTH_BYPASS=true. Two checks so a single env misconfiguration
    # in production doesn't let an attacker claim any org by passing a header.
    if settings.app_env == "dev" and settings.allow_dev_auth_bypass:
        dev_org = request.headers.get("X-Dev-Org-Id")
        if dev_org:
            dev_user = request.headers.get("X-Dev-User-Id", "user_dev")
            return Principal(user_id=dev_user, organization_id=UUID(dev_org))

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth.removeprefix("Bearer ").strip()

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

    # `org_id` is a custom claim populated by the `aki` Clerk JWT template
    # (see docs/architecture.md §3). If the claim is missing — common when
    # the user's session JWT was minted before we backfilled their metadata,
    # or the template returned an empty value — fall back to a DB lookup.
    org_id = claims.get("org_id")
    if not org_id:
        org_id = await _lookup_org_by_clerk_user_id(claims["sub"])
    if not org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no org for this user")
    return Principal(user_id=claims["sub"], organization_id=UUID(str(org_id)))
