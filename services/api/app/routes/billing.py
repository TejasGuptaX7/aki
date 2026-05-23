"""Billing — usage rollup + Stripe meter push.

Today (Phase 2/5 stub):
  - GET  /v1/billing/usage         — sum cost_usd from audit_log payloads
                                     grouped by day, for the current org.
  - POST /v1/billing/rollup        — admin trigger: push usage for the
                                     previous billing window into Stripe
                                     meter events. Idempotent on (org_id,
                                     window_end).

The Stripe meter push is gated on STRIPE_SECRET_KEY being set; without it
the endpoint reports the totals it WOULD push, so dev can verify the math
before wiring Stripe.

Full automation (nightly Stripe push, per-org subscription tier lookup,
hard usage caps) lands when we're ready to take real payments.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.config import get_settings
from app.middleware import get_principal, get_session


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/billing", tags=["billing"])


class UsageDay(BaseModel):
    day: date
    cost_usd: float
    tool_calls: int
    chats: int
    jobs: int


@router.get("/usage", response_model=list[UsageDay])
async def usage(
    days: int = 30,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[UsageDay]:
    if days < 1 or days > 365:
        raise HTTPException(400, "days out of range (1..365)")

    rows = (
        await db.execute(
            text("""
                select
                  date_trunc('day', created_at)::date as day,
                  coalesce(sum((payload->>'cost_usd')::numeric), 0) as cost,
                  sum(case when action = 'chat.tool_call' then 1 else 0 end) as tools,
                  sum(case when action = 'chat.complete' then 1 else 0 end) as chats,
                  sum(case when action = 'job.complete' then 1 else 0 end) as jobs
                from audit_log
                where organization_id = current_setting('app.org_id', true)::uuid
                  and created_at >= now() - (:days || ' days')::interval
                group by 1
                order by 1 desc
            """),
            {"days": days},
        )
    ).mappings().all()

    return [
        UsageDay(
            day=row["day"], cost_usd=float(row["cost"] or 0),
            tool_calls=int(row["tools"] or 0),
            chats=int(row["chats"] or 0),
            jobs=int(row["jobs"] or 0),
        )
        for row in rows
    ]


class RollupResponse(BaseModel):
    window_start: datetime
    window_end: datetime
    cost_usd: float
    stripe_pushed: bool
    stripe_event_id: str | None


@router.post("/rollup", response_model=RollupResponse)
async def rollup(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> RollupResponse:
    """Sum cost for the previous full day (UTC) and (if Stripe is wired)
    push as a meter event. Designed to be hit by a nightly cron."""
    settings = get_settings()

    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    window_start = today - timedelta(days=1)
    window_end = today

    total = (
        await db.execute(
            text("""
                select coalesce(sum((payload->>'cost_usd')::numeric), 0)
                from audit_log
                where organization_id = current_setting('app.org_id', true)::uuid
                  and created_at >= :start and created_at < :end
            """),
            {"start": window_start, "end": window_end},
        )
    ).scalar_one() or 0
    cost = float(total)

    pushed = False
    event_id: str | None = None
    if settings.stripe_secret_key and settings.stripe_meter_event_name and cost > 0:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(
                "https://api.stripe.com/v1/billing/meter_events",
                headers={
                    "Authorization": f"Bearer {settings.stripe_secret_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "event_name": settings.stripe_meter_event_name,
                    "timestamp": str(int(window_end.timestamp())),
                    f"payload[stripe_customer_id]": (
                        settings.stripe_customer_id or str(principal.organization_id)
                    ),
                    f"payload[value]": f"{cost:.4f}",
                    f"identifier": f"{principal.organization_id}:{window_end.date().isoformat()}",
                },
            )
            if r.status_code >= 400:
                log.error("stripe meter push failed: %s %s", r.status_code, r.text)
            else:
                pushed = True
                event_id = r.json().get("id")

    return RollupResponse(
        window_start=window_start, window_end=window_end,
        cost_usd=cost, stripe_pushed=pushed, stripe_event_id=event_id,
    )
