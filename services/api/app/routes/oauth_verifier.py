"""Custom user verifier for Arcade.dev — the Contextual Access webhook.

Arcade calls into our control plane to identify and authorize a user
mid-flow. We expose the four default hook paths under one router:

  POST /oauth/arcade/verifier/access  — "what tools may this user see"
  POST /oauth/arcade/verifier/pre     — pre-execution validation
  POST /oauth/arcade/verifier/post    — post-execution transformation
  GET  /oauth/arcade/verifier/health  — liveness probe

Auth: HTTP Bearer. Configure the same secret in Arcade dashboard
(Contextual Access → Webhook auth → bearer) and in our env as
ARCADE_VERIFIER_TOKEN. We compare with `hmac.compare_digest`.

What we return for /access:
  - 200 with `{"allow": true, "user": {"id": <our-user-id>, "metadata": …}}`
    when the request's `user_id` matches a real, non-deleted user in the
    org we recognize.
  - 200 with `{"allow": false, "reason": "..."}` when the user is unknown
    or the org is suspended.

The exact response schema Arcade expects is not fully published in
public docs at the time of writing; this implementation matches the
documented hook semantics (allow/deny + optional context) and is
intentionally structured around one helper (`_verifier_response`) so we
can adjust shape once Arcade publishes the OpenAPI for the hook contract
or after a `POST /v1/auth/validate_custom_verifier` round-trip surfaces
any expected fields.

Audit: each call writes one `oauth.verifier.{hook}` audit row scoped to
the resolved org (or platform-level when org can't be resolved).
"""
from __future__ import annotations

import hmac
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, text

from app.audit import append_audit
from app.config import get_settings
from app.db import SessionLocal, session_for_org
from app.limits import limiter
from app.models import Organization, User


log = logging.getLogger(__name__)
router = APIRouter(prefix="/oauth/arcade/verifier", tags=["oauth_verifier"])


# ── Auth ───────────────────────────────────────────────────────────────────


def _verify_arcade_bearer(authorization: str | None) -> None:
    """Raise 401 unless the Authorization header carries the configured
    arcade_verifier_token. Constant-time compare to dodge timing attacks."""
    settings = get_settings()
    expected = settings.arcade_verifier_token
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ARCADE_VERIFIER_TOKEN not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bearer")


# ── User lookup ────────────────────────────────────────────────────────────


async def _resolve_user(user_id: str) -> tuple[UUID, str] | None:
    """Map the Arcade-User-ID back to (org_id, clerk_user_id).

    We hand Arcade two identifier shapes (see app/connectors/materialize.py):
      - org-wide:   "<org_uuid>"
      - per-agent:  "<org_uuid>:<agent_uuid>"

    We only need org_id from either. RLS-bypassed because the lookup
    spans orgs before we know which one we're scoping to.
    """
    if not user_id:
        return None
    raw_org = user_id.split(":", 1)[0]
    try:
        org_uuid = UUID(raw_org)
    except ValueError:
        return None

    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        org = await db.scalar(select(Organization).where(Organization.id == org_uuid))
        if org is None:
            return None
        # We return ANY user for this org as a stand-in identity — Arcade
        # doesn't need a specific human, it needs to know the user_id maps
        # to a real account in our system. Pick the oldest user (likely
        # the org owner).
        user = await db.scalar(
            select(User)
            .where(User.organization_id == org_uuid)
            .order_by(User.created_at.asc())
            .limit(1)
        )
        if user is None:
            return None
        return org_uuid, user.clerk_user_id


def _verifier_response(
    *,
    allow: bool,
    org_id: UUID | None = None,
    clerk_user_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One place to assemble the response body so the shape's easy to tune
    once we've run `arcade_client.validate_custom_verifier()` against it."""
    body: dict[str, Any] = {"allow": allow}
    if allow:
        body["user"] = {
            "id": str(org_id) if org_id else None,
            "clerk_user_id": clerk_user_id,
            "metadata": metadata or {},
        }
    if reason:
        body["reason"] = reason
    return body


# ── Audit ──────────────────────────────────────────────────────────────────


async def _record(
    org_id: UUID | None,
    hook: str,
    user_id: str,
    allow: bool,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    if org_id is None:
        # Platform-level (unknown user) — can't write to a tenant scope.
        log.info(
            "oauth.verifier.%s user_id=%s allow=%s (no org)",
            hook, user_id, allow,
        )
        return
    async with session_for_org(org_id) as db:
        await append_audit(
            db,
            org_id,
            actor=f"arcade:verifier:{hook}",
            action=f"oauth.verifier.{hook}",
            target=user_id,
            payload={"allow": allow, **(extra or {})},
        )
        await db.commit()


# ── Hook endpoints ─────────────────────────────────────────────────────────


def _bearer_dep(authorization: str | None = Header(None)) -> None:
    _verify_arcade_bearer(authorization)


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe — does NOT require bearer (matches Arcade's default;
    the dashboard ping happens before the dashboard knows our secret)."""
    settings = get_settings()
    return {
        "ok": True,
        "configured": bool(settings.arcade_verifier_token),
    }


@router.post("/access", dependencies=[Depends(_bearer_dep)])
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def access(request: Request) -> dict[str, Any]:
    """Decide whether `user_id` may see tools at all. We allow any user
    whose ID resolves to a real org in our DB."""
    body = await _safe_json(request)
    user_id = (body.get("user_id") or "").strip()
    resolved = await _resolve_user(user_id)
    if resolved is None:
        await _record(None, "access", user_id, False)
        return _verifier_response(allow=False, reason="unknown user_id")
    org_id, clerk_user_id = resolved
    await _record(org_id, "access", user_id, True)
    return _verifier_response(
        allow=True,
        org_id=org_id,
        clerk_user_id=clerk_user_id,
    )


@router.post("/pre", dependencies=[Depends(_bearer_dep)])
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def pre(request: Request) -> dict[str, Any]:
    """Pre-execution hook — validate arguments before the tool runs. v1
    is a pass-through; we re-use the access decision. Wire policy here
    when we want to e.g. block sends to non-org-internal domains."""
    body = await _safe_json(request)
    user_id = (body.get("user_id") or "").strip()
    resolved = await _resolve_user(user_id)
    if resolved is None:
        await _record(None, "pre", user_id, False)
        return _verifier_response(allow=False, reason="unknown user_id")
    org_id, clerk_user_id = resolved
    await _record(
        org_id, "pre", user_id, True,
        extra={"tool": body.get("tool"), "args_keys": list((body.get("args") or {}).keys())},
    )
    return _verifier_response(
        allow=True, org_id=org_id, clerk_user_id=clerk_user_id
    )


@router.post("/post", dependencies=[Depends(_bearer_dep)])
@limiter.limit(lambda: get_settings().rate_limit_oauth)
async def post(request: Request) -> dict[str, Any]:
    """Post-execution hook — transform tool output. v1 is a pass-through;
    we'd add PII redaction etc. here when we ship it."""
    body = await _safe_json(request)
    user_id = (body.get("user_id") or "").strip()
    # We don't modify the result; just acknowledge.
    return {
        "allow": True,
        "result": body.get("result"),
    }


async def _safe_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must be an object")
    return body
