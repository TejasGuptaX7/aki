"""Lifecycle helpers for the agent_runs table.

A "run" is one logical agent invocation. It exists for the whole duration
of work the agent is doing on behalf of a user — from "start writing the
weekly report" through every internal tool call until the agent says
"done" (or errors out / is canceled).

This module is the source of truth for run state transitions. Callers:

  - routes/runs.py        — user-facing CRUD wrappers
  - scheduler.py          — cron-triggered runs
  - routes/agent_internal — `update_plan` and the implicit `notify_user`
                            don't go through here, but the agent's own
                            progress reporting writes here via update_plan()

Run rows are NOT in the audit log replacement: the audit log stays
per-event (chat.start / chat.tool_call / chat.complete). A run is a
higher-level rollup the UI needs to render "Aki is working on X".

All helpers expect a session that already has RLS scoped via
`session_for_org(org_id)`. They do not commit — that's the caller's job
so the run-write can be batched with the surrounding work (e.g. the
schedule-fire path also wants to update `last_run_at`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun


# Valid step shape — kept as a runtime contract rather than a pydantic
# model because the plan goes straight into JSONB and the agent's MCP
# tool also writes raw dicts. Document here; enforce shallowly.
STEP_KEYS = {"text", "status", "started_at", "completed_at"}
TERMINAL_STATUSES = {"done", "errored", "canceled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_step(step: dict[str, Any]) -> dict[str, Any]:
    """Normalize one plan step. Tolerant of partial input from the agent:
    missing `status` → 'pending'; unknown keys preserved."""
    out = dict(step)
    out.setdefault("text", "")
    out.setdefault("status", "pending")
    out.setdefault("started_at", None)
    out.setdefault("completed_at", None)
    return out


async def create_run(
    db: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    prompt: str,
) -> AgentRun:
    """Open a new run in 'running' state with an empty plan. Caller commits.

    There is no guard against multiple concurrent running rows for the same
    (org, agent) — by design. The UI surfaces the most recent
    non-completed row; older stuck runs need to be canceled or marked
    errored explicitly. The scheduler does check before firing duplicates.
    """
    row = AgentRun(
        id=uuid4(),
        organization_id=org_id,
        agent_id=agent_id,
        status="running",
        plan=[],
        current_index=0,
        prompt=prompt,
        started_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row


async def update_plan(
    db: AsyncSession,
    org_id: UUID,
    run_id: UUID,
    steps: list[dict[str, Any]],
) -> AgentRun | None:
    """Replace the plan wholesale. Returns the updated row or None if not
    found in this org. The agent calls this via the `update_plan` MCP tool
    after deciding (or revising) its plan.

    Plan revisions are idempotent: writing the same plan twice is a no-op
    at the DB level (JSONB compare). We don't try to merge old vs new
    steps — the agent owns the plan, it writes the whole thing each time.
    """
    row = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.organization_id == org_id,
        )
    )
    if row is None:
        return None
    row.plan = [_serialize_step(s) for s in steps]
    await db.flush()
    return row


async def advance(
    db: AsyncSession,
    org_id: UUID,
    run_id: UUID,
    current_index: int,
) -> AgentRun | None:
    """Move the current_index pointer. Also flips the addressed step's
    `status` to 'in_progress' and stamps `started_at`, and marks any
    previously-current step 'done' with `completed_at`.

    The agent does the actual work — this is just bookkeeping for the UI.
    Returns the updated row or None if not found.
    """
    row = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.organization_id == org_id,
        )
    )
    if row is None:
        return None
    if row.status in TERMINAL_STATUSES:
        # Don't let the agent re-advance a finished run; that's a bug on
        # its side. Return the row as-is so the caller can log + ignore.
        return row

    plan = [_serialize_step(s) for s in (row.plan or [])]
    now_iso = _now().isoformat()

    # Mark the previously-current step done (if any and within bounds).
    prev = row.current_index
    if 0 <= prev < len(plan):
        if plan[prev].get("status") != "done":
            plan[prev]["status"] = "done"
            plan[prev]["completed_at"] = now_iso

    # Stamp the new current step in_progress.
    if 0 <= current_index < len(plan):
        plan[current_index]["status"] = "in_progress"
        plan[current_index].setdefault("started_at", now_iso)

    row.plan = plan
    row.current_index = current_index
    await db.flush()
    return row


async def complete(
    db: AsyncSession,
    org_id: UUID,
    run_id: UUID,
    status: str = "done",
    error: str | None = None,
) -> AgentRun | None:
    """Mark a run terminal. `status` ∈ {done, errored, canceled}.

    Also stamps any in-progress step as completed (status=done) on a
    successful finish, so the UI doesn't show a half-done row after a
    successful run.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError(
            f"complete() status must be one of {sorted(TERMINAL_STATUSES)}, "
            f"got {status!r}"
        )
    row = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.organization_id == org_id,
        )
    )
    if row is None:
        return None
    if row.status in TERMINAL_STATUSES:
        # Idempotent: don't overwrite a terminal status. Cancel-after-done
        # is a no-op rather than a 409.
        return row

    row.status = status
    row.completed_at = _now()
    row.error = error

    # If the run finished cleanly, tie off the current step. Errored /
    # canceled runs leave the step state intact so the UI can show where
    # things stopped.
    if status == "done":
        plan = [_serialize_step(s) for s in (row.plan or [])]
        idx = row.current_index
        if 0 <= idx < len(plan) and plan[idx].get("status") == "in_progress":
            plan[idx]["status"] = "done"
            plan[idx]["completed_at"] = _now().isoformat()
        row.plan = plan

    await db.flush()
    return row


async def get_current_run(
    db: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
) -> AgentRun | None:
    """Return the most recent non-completed run for this agent, or None.

    "Most recent" because if a previous run is stuck in `running` after a
    crash, the next start will open a new row — we want to show the
    freshest one to the user. The stale row stays in the table as
    history; an admin sweep can close it later.
    """
    return await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.organization_id == org_id,
            AgentRun.agent_id == agent_id,
            AgentRun.status == "running",
        )
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )


async def list_runs(
    db: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    limit: int = 20,
) -> list[AgentRun]:
    """Newest-first list of runs for an agent. Caller scopes the limit
    (validated at the route layer)."""
    rows = (
        await db.execute(
            select(AgentRun)
            .where(
                AgentRun.organization_id == org_id,
                AgentRun.agent_id == agent_id,
            )
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


def to_wire(run: AgentRun) -> dict[str, Any]:
    """Wire shape for the runs API + frontend consumption. Mirrors the
    pattern used by approvals._to_wire — keep this function the single
    place we shape run rows for HTTP."""
    return {
        "id": str(run.id),
        "agent_id": str(run.agent_id),
        "status": run.status,
        "plan": list(run.plan or []),
        "current_index": run.current_index,
        "prompt": run.prompt,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": (
            run.completed_at.isoformat() if run.completed_at else None
        ),
        "error": run.error,
    }
