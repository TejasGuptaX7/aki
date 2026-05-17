"""GET /billing/usage — per-org spend + activity dashboard.

Reads from two existing sources, no new tables:
  - rate_limits   — daily counters (actions / browser_seconds / llm_cents)
                    that the chat route increments. Cheap, indexed by
                    (org, day). Authoritative for daily totals.
  - audit_log     — chat.complete events carry payload.cost_usd + the
                    agent_id, so we can produce a per-agent breakdown.

No new schema. No background aggregation. Computed live on each request
because the queries are bounded by the time window and indexed.

Wire shape designed for a single-page dashboard:
  {
    "today":   {date, cost_usd, actions, browser_seconds, llm_cents,
                caps: {actions, browser_seconds, llm_cents}},
    "month":   {cost_usd, actions, llm_cents},
    "last_30d_daily":  [{date, cost_usd, actions}, ...],
    "by_agent_30d":    [{agent_id, name, slug, cost_usd, actions}, ...],
  }
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.config import get_settings
from app.middleware import get_principal, get_session
from app.models import Agent, AuditLog, RateLimit


router = APIRouter(prefix="/billing", tags=["billing"])


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _cents_to_usd(c: int | None) -> float:
    return round((c or 0) / 100.0, 4)


@router.get("/usage")
async def usage(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    today = _today_utc()
    org = principal.organization_id

    # ── today + caps (one row from rate_limits) ────────────────────────────
    today_row = await db.scalar(
        select(RateLimit).where(
            RateLimit.organization_id == org,
            RateLimit.period_start == today,
        )
    )
    today_block = {
        "date": today.isoformat(),
        "cost_usd": _cents_to_usd(today_row.llm_cents if today_row else 0),
        "actions": today_row.actions_count if today_row else 0,
        "browser_seconds": today_row.browser_seconds if today_row else 0,
        "llm_cents": today_row.llm_cents if today_row else 0,
        "caps": {
            "actions": settings.rate_limit_daily_actions,
            "browser_seconds": settings.rate_limit_daily_browser_seconds,
            "llm_cents": settings.rate_limit_daily_llm_cents,
        },
    }

    # ── last 30 days bucketed by day (from rate_limits — fast, indexed) ───
    cutoff = today - timedelta(days=29)
    daily_rows = (
        await db.execute(
            select(RateLimit)
            .where(
                RateLimit.organization_id == org,
                RateLimit.period_start >= cutoff,
            )
            .order_by(RateLimit.period_start.asc())
        )
    ).scalars().all()
    last_30d_daily = [
        {
            "date": r.period_start.isoformat(),
            "cost_usd": _cents_to_usd(r.llm_cents),
            "actions": r.actions_count,
        }
        for r in daily_rows
    ]

    # ── month-to-date totals (sum daily rows) ──────────────────────────────
    month_start = today.replace(day=1)
    mtd = {
        "cost_usd": _cents_to_usd(
            sum(r.llm_cents for r in daily_rows if r.period_start >= month_start)
        ),
        "actions": sum(
            r.actions_count for r in daily_rows if r.period_start >= month_start
        ),
        "llm_cents": sum(
            r.llm_cents for r in daily_rows if r.period_start >= month_start
        ),
    }

    # ── by-agent breakdown over last 30 days ─────────────────────────────
    # Pull chat.complete events whose payload has a cost_usd, aggregate in
    # Python. Bounded by org + 30d window so the result set is small even
    # at heavy chat usage.
    since = datetime.now(timezone.utc) - timedelta(days=30)
    audit_rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.organization_id == org,
                AuditLog.action == "chat.complete",
                AuditLog.created_at >= since,
                AuditLog.agent_id.is_not(None),
            )
        )
    ).scalars().all()

    agent_totals: dict[str, dict[str, float | int]] = {}
    for r in audit_rows:
        aid = str(r.agent_id)
        if aid not in agent_totals:
            agent_totals[aid] = {"cost_usd": 0.0, "actions": 0}
        agent_totals[aid]["cost_usd"] = round(
            float(agent_totals[aid]["cost_usd"])
            + float((r.payload or {}).get("cost_usd") or 0.0),
            4,
        )
        agent_totals[aid]["actions"] = int(agent_totals[aid]["actions"]) + 1

    # Hydrate with agent names
    if agent_totals:
        agents = (
            await db.execute(
                select(Agent).where(Agent.organization_id == org)
            )
        ).scalars().all()
        name_by_id = {str(a.id): (a.name, a.slug) for a in agents}
    else:
        name_by_id = {}

    by_agent_30d = sorted(
        [
            {
                "agent_id": aid,
                "name": name_by_id.get(aid, ("(deleted)", "-"))[0],
                "slug": name_by_id.get(aid, ("(deleted)", "-"))[1],
                **totals,
            }
            for aid, totals in agent_totals.items()
        ],
        key=lambda x: float(x["cost_usd"]),
        reverse=True,
    )

    return {
        "today": today_block,
        "month": mtd,
        "last_30d_daily": last_30d_daily,
        "by_agent_30d": by_agent_30d,
        "platform_cap_cents": settings.platform_daily_spend_cap_cents,
    }
