"""Aki desktop device pairing.

Two-step pair so the desktop never sees the user's Clerk session token:

  1. Web app (Clerk-authed) calls POST /v1/devices/pair/start. We mint a
     6-digit code, stash it in Redis with a 5-minute TTL, and return it.
  2. Desktop client prompts the user for the code, then calls
     POST /v1/devices/pair/complete with the code, a friendly name, and an
     Ed25519 pubkey. We verify the code, create an aki_devices row, and
     return a device JWT signed by our own Ed25519 signing key.

The device JWT is long-lived (30 days) and is verified by `auth.verify`
when the `iss` claim is `aki-api`. Revoking a row in aki_devices sets
`revoked_at`, which `_lookup_user_and_orgs_for_device` checks on every call.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import DEVICE_JWT_AUDIENCE, DEVICE_JWT_ISSUER, Principal
from app.config import get_settings
from app.middleware import get_principal, get_session
from app.models import AkiDevice, User


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/devices", tags=["devices"])

PAIR_CODE_TTL_SECONDS = 5 * 60
DEVICE_JWT_LIFETIME = timedelta(days=30)


_redis_pool: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    """Lazy redis connection, reused across requests."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis_pool


def _pair_key(code: str) -> str:
    return f"aki:device-pair:{code}"


class PairStartResponse(BaseModel):
    code: str
    expires_in_seconds: int


@router.post("/pair/start", response_model=PairStartResponse)
async def pair_start(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> PairStartResponse:
    # 6 digits is plenty for a 5-minute live window. Use secrets.randbelow
    # rather than random.randint so an attacker can't reproduce the code.
    code = f"{secrets.randbelow(1_000_000):06d}"

    # Look up the internal user_id for the principal so we can stash both.
    user_id = (
        await db.execute(
            select(User.id).where(User.clerk_user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    if user_id is None:
        raise HTTPException(404, "user not found (webhook not yet processed?)")

    await _redis().set(
        _pair_key(code),
        json.dumps(
            {
                "user_id": str(user_id),
                "organization_id": str(principal.organization_id),
                "clerk_user_id": principal.user_id,
            }
        ),
        ex=PAIR_CODE_TTL_SECONDS,
    )

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="device.pair_start",
        target=None,
        payload={"ttl_s": PAIR_CODE_TTL_SECONDS},
    )
    await db.commit()

    return PairStartResponse(code=code, expires_in_seconds=PAIR_CODE_TTL_SECONDS)


class PairCompleteBody(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    name: str = Field(..., min_length=1, max_length=255)
    pubkey: str = Field(..., min_length=16, max_length=4096)


class PairCompleteResponse(BaseModel):
    device_id: UUID
    device_jwt: str
    expires_at: datetime


@router.post("/pair/complete", response_model=PairCompleteResponse)
async def pair_complete(
    body: PairCompleteBody, request: Request
) -> PairCompleteResponse:
    """Public endpoint — the desktop client has no Clerk session. The 6-digit
    code is the auth here; rate-limit later when we wire slowapi storage."""
    settings = get_settings()
    if not settings.device_jwt_signing_key:
        raise HTTPException(503, "device JWT signing key not configured")

    raw = await _redis().get(_pair_key(body.code))
    if raw is None:
        raise HTTPException(400, "pair code invalid or expired")
    # One-shot: consume immediately so a leaked code can't be reused.
    await _redis().delete(_pair_key(body.code))

    payload = json.loads(raw)
    user_id = UUID(payload["user_id"])
    organization_id = UUID(payload["organization_id"])
    clerk_user_id = payload["clerk_user_id"]

    from app.db import session_for_org
    device_id = uuid4()
    jti = secrets.token_urlsafe(16)
    expires = datetime.now(tz=timezone.utc) + DEVICE_JWT_LIFETIME

    async with session_for_org(organization_id) as db:
        db.add(
            AkiDevice(
                id=device_id,
                user_id=user_id,
                organization_id=organization_id,
                name=body.name,
                pubkey=body.pubkey,
                device_jwt_jti=jti,
            )
        )
        await append_audit(
            db,
            organization_id,
            actor=clerk_user_id,
            action="device.pair_complete",
            target=str(device_id),
            payload={"name": body.name},
        )
        await db.commit()

    token = jwt.encode(
        {
            "iss": DEVICE_JWT_ISSUER,
            "aud": DEVICE_JWT_AUDIENCE,
            "sub": str(device_id),
            "user_id": str(user_id),
            "org_id": str(organization_id),
            "jti": jti,
            "exp": expires,
        },
        settings.device_jwt_signing_key,
        algorithm="EdDSA",
    )

    return PairCompleteResponse(
        device_id=device_id, device_jwt=token, expires_at=expires
    )


class DeviceOut(BaseModel):
    id: UUID
    name: str
    last_seen_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[DeviceOut]:
    # Look up internal user_id, then list their devices in this org.
    user_id = (
        await db.execute(
            select(User.id).where(User.clerk_user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    if user_id is None:
        return []

    rows = (
        await db.execute(
            select(AkiDevice)
            .where(AkiDevice.user_id == user_id)
            .where(AkiDevice.organization_id == principal.organization_id)
            .order_by(AkiDevice.created_at.desc())
        )
    ).scalars().all()
    return [
        DeviceOut(
            id=r.id,
            name=r.name,
            last_seen_at=r.last_seen_at,
            revoked_at=r.revoked_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: UUID,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    # Verify the device belongs to the calling principal's user, then
    # mark revoked. We don't delete the row so the audit chain is preserved.
    user_id = (
        await db.execute(
            select(User.id).where(User.clerk_user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    if user_id is None:
        raise HTTPException(404, "user not found")

    row = (
        await db.execute(
            select(AkiDevice).where(
                AkiDevice.id == device_id,
                AkiDevice.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "device not found")

    if row.revoked_at is None:
        row.revoked_at = datetime.now(tz=timezone.utc)
        await append_audit(
            db,
            principal.organization_id,
            actor=principal.user_id,
            action="device.revoke",
            target=str(device_id),
            payload={"name": row.name},
        )
        await db.commit()
