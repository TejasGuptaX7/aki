"""Clerk JWT verification.

Stub: in dev, accepts a header `X-Dev-Org-Id` so the API works without Clerk
configured. In staging/prod, verifies RS256 against the Clerk JWKS.
"""
from dataclasses import dataclass
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, Request, status

from app.config import get_settings

settings = get_settings()
_jwks_cache: dict | None = None


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

    # `org_id` is a custom claim populated by a Clerk JWT template that
    # joins on our users table; see docs/architecture.md §3.
    org_id = claims.get("org_id")
    if not org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no org for this user")
    return Principal(user_id=claims["sub"], organization_id=UUID(org_id))
