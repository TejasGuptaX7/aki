"""APScheduler tick — re-enqueues scheduled jobs.

We don't use APScheduler's persistent JobStore (we have our own `jobs`
table). The scheduler runs a single recurring tick that:

  1. SELECTs `jobs WHERE schedule_cron IS NOT NULL AND next_run_at <= now()`
  2. For each row: enqueues `dispatch_job(job_id, org_id)` onto the arq
     queue and sets a new `next_run_at` from the cron expression.

Cron expressions are evaluated with `croniter` if available; falls back to
parsing the standard 5-field format ourselves for the few common cases
(minute, hour, daily). We bias toward the conservative interpretation
(every minute ticks the scheduler, but the job is only enqueued once per
matched window thanks to next_run_at advancement).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from app.db import SessionLocal

log = logging.getLogger("aki.scheduler")

SCHEDULER_TICK_SECONDS = 30
BILLING_TICK_HOUR_UTC = 1       # 01:00 UTC nightly
CONSOLIDATION_TICK_HOUR_UTC = 3   # 03:00 UTC nightly
RETENTION_TICK_HOUR_UTC = 4       # 04:00 UTC nightly


async def scheduler_loop() -> None:
    """Run forever in the FastAPI lifespan. Cancel on shutdown.

    Two responsibilities:
      1. Every SCHEDULER_TICK_SECONDS, re-enqueue any due cron jobs.
      2. Once per day at BILLING_TICK_HOUR_UTC, run the billing rollup
         for every org with audit activity in the previous day.
    """
    last_billing_day = None
    last_consolidation_day = None
    last_retention_day = None
    while True:
        try:
            n = await _tick()
            if n:
                log.info("scheduler tick: enqueued %d job(s)", n)
        except Exception:
            log.exception("scheduler tick failed")

        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        try:
            if now_utc.hour == BILLING_TICK_HOUR_UTC and last_billing_day != today:
                count = await _billing_tick()
                log.info("billing tick: rolled up %d org(s) for %s",
                         count, today - timedelta(days=1))
                last_billing_day = today
        except Exception:
            log.exception("billing tick failed")

        try:
            if now_utc.hour == CONSOLIDATION_TICK_HOUR_UTC and last_consolidation_day != today:
                count = await _consolidation_tick()
                log.info("consolidation tick: processed %d org(s)", count)
                last_consolidation_day = today
        except Exception:
            log.exception("consolidation tick failed")

        try:
            if now_utc.hour == RETENTION_TICK_HOUR_UTC and last_retention_day != today:
                count = await _retention_tick()
                log.info("retention tick: processed %d org(s)", count)
                last_retention_day = today
        except Exception:
            log.exception("retention tick failed")

        await asyncio.sleep(SCHEDULER_TICK_SECONDS)


async def _billing_tick() -> int:
    """For each org with any audit activity in the previous UTC day, sum
    cost_usd and upsert a `billing_usage` row. Idempotent on (org, day).
    Stripe push is gated on STRIPE_SECRET_KEY being set.
    """
    from app.db import SessionLocal
    from app.config import get_settings

    settings = get_settings()
    rolled = 0

    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    window_start = today - timedelta(days=1)
    window_end = today
    day = window_start.date()

    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        orgs = (
            await db.execute(
                text("""
                    select distinct organization_id
                    from audit_log
                    where created_at >= :start and created_at < :end
                """),
                {"start": window_start, "end": window_end},
            )
        ).scalars().all()

        for org_id in orgs:
            row = (
                await db.execute(
                    text("""
                        select
                          coalesce(sum((payload->>'cost_usd')::numeric), 0) as cost,
                          sum(case when action='chat.complete' then 1 else 0 end) as chats,
                          sum(case when action='job.complete' then 1 else 0 end) as jobs,
                          sum(case when action='chat.tool_call' then 1 else 0 end) as tools
                        from audit_log
                        where organization_id = :org
                          and created_at >= :start and created_at < :end
                    """),
                    {"org": str(org_id), "start": window_start, "end": window_end},
                )
            ).mappings().one()

            await db.execute(
                text("""
                    insert into billing_usage
                      (organization_id, day, cost_usd, chat_count, job_count,
                       tool_call_count, breakdown)
                    values
                      (:org, :day, :cost, :chats, :jobs, :tools, '{}'::jsonb)
                    on conflict (organization_id, day) do update set
                      cost_usd = excluded.cost_usd,
                      chat_count = excluded.chat_count,
                      job_count = excluded.job_count,
                      tool_call_count = excluded.tool_call_count,
                      updated_at = now()
                """),
                {
                    "org": str(org_id),
                    "day": day,
                    "cost": row["cost"] or 0,
                    "chats": row["chats"] or 0,
                    "jobs": row["jobs"] or 0,
                    "tools": row["tools"] or 0,
                },
            )
            rolled += 1

        await db.commit()

    return rolled


async def _consolidation_tick() -> int:
    """Run memory consolidation for every active organization."""
    from app.brain.consolidation import run_consolidation
    from app.db import SessionLocal

    processed = 0
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        orgs = (
            await db.execute(
                text("""
                    select distinct organization_id
                    from audit_log
                    where created_at >= now() - interval '1 day'
                """)
            )
        ).scalars().all()

        for org_id in orgs:
            try:
                await run_consolidation(db, org_id)
                processed += 1
            except Exception:
                log.exception("consolidation failed for org=%s", org_id)

        await db.commit()
    return processed


async def _retention_tick() -> int:
    """Run data retention enforcement for all organizations."""
    from app.retention import retention_tick
    return await retention_tick()


async def _tick() -> int:
    """Find due cron jobs, enqueue them, advance next_run_at."""
    from app.worker import enqueue_job

    # We need to read across orgs without RLS, so bypass row_security on this
    # session only. The scheduler is a privileged background loop, not a
    # user-facing handler.
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        rows = (
            await db.execute(
                text("""
                    select id, organization_id, schedule_cron, next_run_at
                    from jobs
                    where schedule_cron is not null
                      and next_run_at is not null
                      and next_run_at <= now()
                      and status not in ('running', 'cancelled')
                    order by next_run_at asc
                    limit 100
                """)
            )
        ).mappings().all()

        enqueued = 0
        for row in rows:
            job_id = UUID(str(row["id"]))
            org_id = UUID(str(row["organization_id"]))
            cron_expr = row["schedule_cron"]
            try:
                nxt = _next_fire(cron_expr,
                                 row["next_run_at"] or datetime.now(timezone.utc))
            except Exception:
                log.exception("bad cron expression on job %s: %r", job_id, cron_expr)
                continue

            await db.execute(
                text("""
                    update jobs set status='queued', next_run_at = :nxt,
                                    updated_at = now()
                    where id = :id
                """),
                {"id": str(job_id), "nxt": nxt},
            )
            await enqueue_job(job_id, org_id)
            enqueued += 1

        await db.commit()
        return enqueued


def _next_fire(cron_expr: str, after: datetime) -> datetime:
    """Compute the next fire time after `after`. Prefer croniter if present."""
    try:
        from croniter import croniter
        return croniter(cron_expr, after).get_next(datetime)
    except ImportError:
        # Minimal fallback: support a handful of common shorthands so the
        # absence of croniter doesn't break dev. Production should install
        # croniter via the optional extras.
        if cron_expr in ("@hourly", "0 * * * *"):
            return (after.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1))
        if cron_expr in ("@daily", "0 0 * * *"):
            return (after.replace(hour=0, minute=0, second=0, microsecond=0)
                    + timedelta(days=1))
        # Default: bump by 1 hour and let the user install croniter.
        log.warning("no croniter installed; bumping cron job by 1h (was %r)",
                    cron_expr)
        return after + timedelta(hours=1)
