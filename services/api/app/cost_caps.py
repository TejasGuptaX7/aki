"""Per-organization cost cap enforcement.

Organizations can set hard and soft spending caps via the admin console:
  - Soft cap: warns the user but allows the operation
  - Hard cap: blocks new chat turns and job dispatches

Caps are checked against the current day's accumulated cost from audit_log.
For efficiency, daily costs are cached in Redis with a 60s TTL.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

import redis.asyncio as redis
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

log = logging.getLogger(__name__)

_COST_PREFIX = "cost:daily"
_CACHE_TTL_S = 60


async def _redis() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


async def _get_daily_cost(db: AsyncSession, org_id: UUID) -> float:
    """Sum cost_usd for the current UTC day from audit_log.

    Uses Redis as a cache to avoid hammering Postgres on every request."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    cache_key = f"{_COST_PREFIX}:{org_id}:{today}"

    try:
        r = await _redis()
        cached = await r.get(cache_key)
        if cached is not None:
            return float(cached)
    except Exception:
        pass  # Redis down — fall through to DB

    result = await db.execute(
        text("""
            select coalesce(sum((payload->>'cost_usd')::numeric), 0)
            from audit_log
            where organization_id = :org
              and created_at >= date_trunc('day', now() at time zone 'utc')
        """),
        {"org": str(org_id)},
    )
    cost = float(result.scalar_one() or 0)

    try:
        r = await _redis()
        await r.setex(cache_key, _CACHE_TTL_S, str(cost))
    except Exception:
        pass

    return cost


async def check_spend_cap(
    db: AsyncSession,
    org_id: UUID,
    *,
    estimated_cost: float = 0.0,
) -> tuple[bool, str]:
    """Check whether the org has exceeded its spending cap.

    Returns (allowed, message). If allowed is False, the caller should
    raise an HTTPException.
    """
    from app.feature_flags import is_enabled

    if not await is_enabled("cost_caps", org_id):
        return True, ""
    # Fetch org settings from the JSONB column
    row = await db.execute(
        text("""
            select settings from organizations
            where id = :org
        """),
        {"org": str(org_id)},
    )
    settings_row = row.scalar_one_or_none()
    caps = settings_row or {}
    if isinstance(caps, str):
        import json

        try:
            caps = json.loads(caps)
        except Exception:
            caps = {}

    hard_cap = caps.get("spend_cap_hard")
    soft_cap = caps.get("spend_cap_soft")

    if hard_cap is None and soft_cap is None:
        return True, ""

    current = await _get_daily_cost(db, org_id)
    projected = current + estimated_cost

    if hard_cap is not None and projected >= hard_cap:
        msg = (
            f"Daily spend cap exceeded: ${projected:.2f} / ${hard_cap:.2f}. "
            f"Contact your org admin to increase the cap."
        )
        log.warning(
            "spend_cap_hard blocked org=%s projected=%.2f cap=%.2f", org_id, projected, hard_cap
        )
        return False, msg

    if soft_cap is not None and projected >= soft_cap:
        return True, (
            f"Warning: daily spend approaching soft cap " f"(${projected:.2f} / ${soft_cap:.2f})"
        )

    return True, ""


async def enforce_spend_cap(
    db: AsyncSession,
    org_id: UUID,
    *,
    estimated_cost: float = 0.0,
) -> None:
    """Raise HTTPException(402) if the hard cap is exceeded."""
    allowed, msg = await check_spend_cap(db, org_id, estimated_cost=estimated_cost)
    if not allowed:
        raise HTTPException(402, msg)
