"""Per-org daily caps + global platform circuit breaker.

We are launching free + invite-only with no payment integration. The cost
floor for abuse is therefore set in code, not by the customer's credit card:

  * Per-org daily caps — actions / browser seconds / LLM cents. Refused
    cleanly with a friendly 429 when reached. Caps reset at UTC midnight.
  * Global circuit breaker — total platform spend across all orgs. If it
    exceeds the daily ceiling, new signups are blocked (existing orgs still
    work). Operator sees the alert and either tunes caps or invites
    fewer users in the next batch.

All counters live in the `rate_limits` table (one row per (org, day)).
Atomicity comes from a Postgres INSERT … ON CONFLICT … DO UPDATE that does
the compare-and-set in a single statement.

Configurable knobs in app/config.py:
  rate_limit_daily_actions          actions per org per day        (default 500)
  rate_limit_daily_browser_seconds  browser-harness seconds per org (default 3600 = 60 min)
  rate_limit_daily_llm_cents        LLM spend cents per org         (default 5000 = $50)
  platform_daily_spend_cap_cents    total platform $ ceiling        (default 50000 = $500)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import RateLimit


log = logging.getLogger(__name__)


class Kind(str, Enum):
    """Counter kinds. The string value matches the DB column name so we can
    use it as a parameter without a translation step."""
    ACTIONS = "actions_count"
    BROWSER_SECONDS = "browser_seconds"
    LLM_CENTS = "llm_cents"


_FRIENDLY_NAME: dict[Kind, str] = {
    Kind.ACTIONS: "agent actions",
    Kind.BROWSER_SECONDS: "browser harness time",
    Kind.LLM_CENTS: "LLM spend",
}


def _cap_for(kind: Kind) -> int:
    s = get_settings()
    if kind is Kind.ACTIONS:
        return s.rate_limit_daily_actions
    if kind is Kind.BROWSER_SECONDS:
        return s.rate_limit_daily_browser_seconds
    if kind is Kind.LLM_CENTS:
        return s.rate_limit_daily_llm_cents
    raise ValueError(f"unknown kind {kind!r}")


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


async def _current_usage(
    db: AsyncSession, org_id: UUID, day: date
) -> RateLimit | None:
    return await db.scalar(
        select(RateLimit).where(
            RateLimit.organization_id == org_id,
            RateLimit.period_start == day,
        )
    )


async def enforce_daily_cap(
    db: AsyncSession, org_id: UUID, kind: Kind
) -> None:
    """Raise 429 with a clean message if the org has hit today's cap.

    Read-only — does NOT increment. Call record_usage() after the action
    completes successfully (so failed requests don't burn quota).

    The race window between this check and the eventual record_usage means
    a flood can briefly exceed the cap by N-concurrent-requests. For v1
    abuse defense this is acceptable (we care about preventing 1000x
    overruns, not 1.1x).
    """
    row = await _current_usage(db, org_id, _today_utc())
    used = 0 if row is None else getattr(row, kind.value)
    cap = _cap_for(kind)
    if used >= cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "daily_cap_reached",
                "kind": kind.value,
                "friendly": _FRIENDLY_NAME[kind],
                "used": used,
                "cap": cap,
                "resets_at": "00:00 UTC",
                "message": (
                    f"Hit today's {_FRIENDLY_NAME[kind]} cap ({used}/{cap}). "
                    "Resets at midnight UTC."
                ),
            },
        )


async def record_usage(
    db: AsyncSession,
    org_id: UUID,
    kind: Kind,
    amount: int = 1,
) -> None:
    """Atomically add `amount` to today's counter for this kind. Inserts the
    row if it's the first counter of the day.

    Uses Postgres ON CONFLICT to avoid the race between
    SELECT-then-UPDATE — two concurrent calls always produce the correct
    sum, never a lost-update."""
    if amount <= 0:
        return
    column = kind.value
    # Parameter binding can't touch column names; whitelist via the enum.
    sql = text(f"""
        INSERT INTO rate_limits (organization_id, period_start, {column})
        VALUES (:oid, :day, :delta)
        ON CONFLICT (organization_id, period_start)
        DO UPDATE SET {column} = rate_limits.{column} + EXCLUDED.{column}
    """)
    await db.execute(
        sql,
        {"oid": str(org_id), "day": _today_utc(), "delta": amount},
    )


async def platform_daily_spend_cents(db: AsyncSession) -> int:
    """Sum llm_cents across all orgs for today. Cheap: one indexed query.

    Bypasses RLS for the duration of this query because there's no single
    org context for a platform-wide aggregate. Same pattern as
    auth.py::_lookup_org_by_clerk_user_id."""
    today = _today_utc()
    await db.execute(text("SET LOCAL row_security = off"))
    total = await db.scalar(
        select(func.coalesce(func.sum(RateLimit.llm_cents), 0))
        .where(RateLimit.period_start == today)
    )
    return int(total or 0)


async def check_global_circuit_breaker(db: AsyncSession) -> None:
    """Raise 503 if platform-wide spend is over the cap. Called on signup
    (and any other gated entry point) so abusers can't onboard during a
    cost spike. Existing orgs keep working — their per-org caps still
    apply, the platform cap is for NEW load."""
    spent = await platform_daily_spend_cents(db)
    cap = get_settings().platform_daily_spend_cap_cents
    if spent >= cap:
        log.warning(
            "global circuit breaker tripped: spent=%d cap=%d", spent, cap
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "platform_circuit_breaker",
                "message": (
                    "Aki is over its daily cost budget — new signups are "
                    "paused until midnight UTC. Existing users are unaffected."
                ),
                "spent_usd": round(spent / 100.0, 2),
                "cap_usd": round(cap / 100.0, 2),
            },
        )
