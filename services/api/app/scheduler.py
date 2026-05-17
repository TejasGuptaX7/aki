"""APScheduler-based cron runner for agent_schedules + the shared
dispatch_run helper used by both the scheduler and POST /agents/{id}/runs.

Lifecycle (driven from main.py's lifespan):

  start()  → AsyncIOScheduler instance, load every enabled row from
             agent_schedules into the scheduler as a CronTrigger job,
             and start the scheduler.
  stop()   → graceful shutdown.

On cron fire:

  _fire_schedule(schedule_id)
    1. RLS-bypass read of the schedule row (we don't have org context yet)
    2. RLS-scoped: open run via agent_runs.create_run, audit `run.start`
    3. Update last_run_at + next_run_at on the schedule
    4. asyncio.create_task(dispatch_run(...)) — fire-and-forget

dispatch_run(org_id, agent_id, run_id, prompt, trigger)
  This is the chat-invocation path Slack uses internally. It composes a
  synthetic user message, opens the per-org container, streams the
  OpenAI-compatible response from the supervisor, accumulates the
  assistant's visible text, and marks the run terminal (done | errored).
  Both scheduled fires AND POST /agents/{id}/runs route through here.

CRUD on agent_schedules (add / remove / update enabled-flag) goes through
this module's `add_schedule`, `remove_schedule`, `replace_schedule` so the
in-process scheduler stays in sync with the DB. Routes call these after
their own DB commit.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from app import agent_runs as runs_mod
from app.audit import append_audit
from app.db import SessionLocal, session_for_org
from app.models import Agent, AgentSchedule


log = logging.getLogger(__name__)


# Single in-process scheduler. None until start() runs. Module-level so the
# CRUD helpers (called from routes) can manipulate it without passing it
# around through dependency injection.
_scheduler: AsyncIOScheduler | None = None


# ── Public lifecycle ───────────────────────────────────────────────────────


async def start() -> None:
    """Create the scheduler and register every enabled schedule. Idempotent:
    calling start() twice is a no-op."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Load every enabled schedule across ALL orgs. We bypass RLS for this
    # one read because the scheduler is a global service, not request-scoped.
    rows = await _load_enabled_schedules()
    for row in rows:
        _add_job(row)

    _scheduler.start()
    log.info("scheduler started with %d enabled schedule(s)", len(rows))


async def stop() -> None:
    """Shutdown — called from FastAPI lifespan teardown."""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        log.exception("scheduler shutdown raised")
    _scheduler = None


# ── CRUD bridges (called by routes/schedules.py) ───────────────────────────


def add_schedule(row: AgentSchedule) -> None:
    """Register a fresh schedule row with the running scheduler. Caller has
    already committed it to the DB."""
    if _scheduler is None or not row.enabled:
        return
    _add_job(row)


def remove_schedule(schedule_id: UUID) -> None:
    """Remove a schedule job. Safe to call for ids the scheduler never had
    (delete of a never-enabled row)."""
    if _scheduler is None:
        return
    job_id = _job_id(schedule_id)
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        # JobLookupError → job wasn't registered; not an error.
        pass


def replace_schedule(row: AgentSchedule) -> None:
    """Re-register after an update (cron / prompt / enabled changed). Drops
    the prior job and re-adds if still enabled."""
    remove_schedule(row.id)
    add_schedule(row)


# ── Dispatcher: invoke an agent on behalf of a run ─────────────────────────


# Time budget for one scheduled run. Long enough for a thoughtful agent
# (search → summarize → draft → notify), short enough that we don't pin
# the supervisor on a runaway. Tune later from real traffic.
DISPATCH_TIMEOUT_S = 600.0


async def dispatch_run(
    org_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    prompt: str,
    trigger: str = "schedule",
) -> None:
    """Drive one agent_run from open to terminal. Imports happen lazily so
    `from app.scheduler import dispatch_run` doesn't drag the container
    runtime into the import graph at module load.

    Mirrors the Slack background-process pattern: open the per-org
    container, post to the supervisor's /v1/chat/completions, accumulate
    visible content, then `complete()` the run with the final status.
    """
    from app.agent_runtime import ensure_agent_loaded
    from app.config import get_settings

    log.info(
        "dispatch_run start org=%s agent=%s run=%s trigger=%s",
        org_id, agent_id, run_id, trigger,
    )

    settings = get_settings()
    error_msg: str | None = None
    final_status = "done"

    try:
        async with session_for_org(org_id) as db:
            agent = await db.scalar(
                select(Agent).where(
                    Agent.id == agent_id,
                    Agent.organization_id == org_id,
                    Agent.status == "active",
                )
            )
            if agent is None:
                error_msg = "agent not found or not active"
                final_status = "errored"
                await _mark_terminal(org_id, run_id, final_status, error_msg)
                return

            container = await ensure_agent_loaded(db, org_id, agent.id)
            await append_audit(
                db, org_id,
                actor=f"runner:{trigger}",
                action="run.dispatch",
                target=str(run_id),
                payload={"container_id": container.container_id[:12]},
                agent_id=agent.id,
            )
            await db.commit()

            # Synthetic user message: tells the agent there's no human
            # waiting, so it should use update_plan() + notify_user() to
            # report progress and completion instead of just streaming
            # text to nowhere.
            composed_user = (
                f"You're running unattended (trigger: {trigger}). The user "
                f"will see your progress via update_plan() and notify_user() "
                f"calls. Goal:\n\n{prompt}\n\n"
                f"Plan the work with update_plan(), execute it step by step, "
                f"and end with notify_user(title='Done: ...', body='...') "
                f"summarizing what you did. If you hit a wall, "
                f"notify_user(title='Stuck: ...', body='...') and stop."
            )
            body = {
                "model": "hermes-agent",
                "stream": True,
                "messages": [
                    {"role": "system", "content": agent.system_prompt},
                    {"role": "user", "content": composed_user},
                ],
            }
            headers = {
                "Authorization": f"Bearer {container.supervisor_api_key}",
                "Content-Type": "application/json",
                "X-Aki-Agent-Id": str(agent.id),
            }
            base_url = container.base_url

        # Streaming happens OUTSIDE the session_for_org block — long-running
        # network IO shouldn't hold a DB connection. We re-open sessions
        # below for any audit writes.
        try:
            await _stream_chat(base_url, body, headers)
        except asyncio.TimeoutError:
            error_msg = f"dispatch timed out after {DISPATCH_TIMEOUT_S}s"
            final_status = "errored"
            log.warning("dispatch_run timeout org=%s run=%s", org_id, run_id)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:300]}"
            final_status = "errored"
            log.exception("dispatch_run failed org=%s run=%s", org_id, run_id)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)[:300]}"
        final_status = "errored"
        log.exception("dispatch_run setup failed org=%s run=%s", org_id, run_id)

    await _mark_terminal(org_id, run_id, final_status, error_msg)


async def _stream_chat(base_url: str, body: dict, headers: dict) -> None:
    """Open the supervisor stream, drain it. We don't capture the assistant's
    text here — for unattended runs, the agent's `notify_user` MCP tool is
    how state escapes; freeform text just disappears.

    Why drain instead of returning the stream: the upstream needs to be
    fully consumed for the supervisor's per-profile rate-limit + audit hooks
    to fire correctly. Closing early can leave the upstream hung.
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(DISPATCH_TIMEOUT_S, connect=10.0)
    ) as c:
        async with c.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            json=body,
            headers=headers,
        ) as upstream:
            async for _ in upstream.aiter_bytes():
                pass


async def _mark_terminal(
    org_id: UUID, run_id: UUID, status: str, error: str | None
) -> None:
    """Open a fresh session and complete the run row. Logged-and-swallowed
    failures here would leave a run stuck in 'running' forever — keep it
    minimal and let any exception propagate to the asyncio.create_task
    handler (which logs it via task.exception())."""
    async with session_for_org(org_id) as db:
        await runs_mod.complete(db, org_id, run_id, status=status, error=error)
        await append_audit(
            db, org_id,
            actor="runner:scheduler",
            action=f"run.{status}",
            target=str(run_id),
            payload={"error": (error or "")[:300]} if error else {},
        )
        await db.commit()


# ── Internal: load + register jobs ─────────────────────────────────────────


def _job_id(schedule_id: UUID) -> str:
    return f"schedule:{schedule_id}"


async def _load_enabled_schedules() -> list[AgentSchedule]:
    """Read every enabled schedule across all orgs. RLS-bypassed because
    the scheduler isn't request-scoped to one org."""
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        rows = (
            await db.execute(
                select(AgentSchedule).where(AgentSchedule.enabled.is_(True))
            )
        ).scalars().all()
    return list(rows)


def _add_job(row: AgentSchedule) -> None:
    """Register one schedule with the running scheduler. Updates the
    DB-side next_run_at lazily (apscheduler computes the next fire time
    itself; we just mirror it after the job runs)."""
    assert _scheduler is not None, "scheduler not started"
    try:
        trigger = CronTrigger.from_crontab(row.cron, timezone="UTC")
    except ValueError as e:
        # Invalid cron strings shouldn't be in the DB (POST validates
        # before insert) — but if one slipped through, log and skip
        # instead of crashing the whole scheduler.
        log.error(
            "skipping schedule %s with invalid cron %r: %s",
            row.id, row.cron, e,
        )
        return

    org_id = row.organization_id
    agent_id = row.agent_id
    schedule_id = row.id
    prompt = row.prompt

    _scheduler.add_job(
        _fire_schedule,
        trigger=trigger,
        id=_job_id(schedule_id),
        replace_existing=True,
        kwargs={
            "schedule_id": schedule_id,
            "org_id": org_id,
            "agent_id": agent_id,
            "prompt": prompt,
        },
        coalesce=True,           # if we missed N fires while down, run 1
        max_instances=1,          # never overlap fires of the same schedule
        misfire_grace_time=60,
    )


async def _fire_schedule(
    schedule_id: UUID,
    org_id: UUID,
    agent_id: UUID,
    prompt: str,
) -> None:
    """The cron-trigger callback: open a run row, stamp the schedule's
    last_run_at, kick off dispatch."""
    log.info(
        "schedule firing: schedule=%s org=%s agent=%s",
        schedule_id, org_id, agent_id,
    )
    try:
        async with session_for_org(org_id) as db:
            run = await runs_mod.create_run(db, org_id, agent_id, prompt)
            schedule = await db.scalar(
                select(AgentSchedule).where(
                    AgentSchedule.id == schedule_id,
                    AgentSchedule.organization_id == org_id,
                )
            )
            if schedule is not None:
                schedule.last_run_at = datetime.now(timezone.utc)
                # next_run_at is whatever apscheduler thinks; pull it back
                # from the live job for the UI to display.
                next_fire = _next_fire_for(schedule_id)
                if next_fire is not None:
                    schedule.next_run_at = next_fire
            await append_audit(
                db, org_id,
                actor="scheduler",
                action="schedule.fire",
                target=str(schedule_id),
                payload={"run_id": str(run.id)},
                agent_id=agent_id,
            )
            await db.commit()
            run_id = run.id
    except Exception:
        log.exception(
            "schedule fire setup failed schedule=%s org=%s",
            schedule_id, org_id,
        )
        return

    asyncio.create_task(
        dispatch_run(org_id, agent_id, run_id, prompt, trigger="schedule")
    )


def _next_fire_for(schedule_id: UUID) -> datetime | None:
    """Look up the next fire time apscheduler computed, in UTC."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_job_id(schedule_id))
    if job is None or job.next_run_time is None:
        return None
    # APScheduler returns timezone-aware datetime; normalize to UTC.
    nrt = job.next_run_time
    if nrt.tzinfo is None:
        return nrt.replace(tzinfo=timezone.utc)
    return nrt.astimezone(timezone.utc)


# ── Hibernation helper ─────────────────────────────────────────────────────


async def orgs_with_running_runs() -> set[UUID]:
    """Return the set of org ids that currently have at least one agent_run
    in status='running'. Used by hibernation to skip those orgs so a
    long-running unattended task doesn't have its container yanked.

    RLS-bypassed because we ask across all orgs.
    """
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        from app.models import AgentRun  # local import: avoid cycles at module load
        rows = (
            await db.execute(
                select(AgentRun.organization_id).where(
                    AgentRun.status == "running"
                ).distinct()
            )
        ).all()
    return {r[0] for r in rows}


# ── Tiny utility (kept for symmetry with the existing routers) ─────────────


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, sort_keys=True)
    except Exception:
        return "<unserializable>"
