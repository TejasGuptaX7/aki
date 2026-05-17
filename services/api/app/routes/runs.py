"""/agents/{id}/runs — long-running agent invocations.

A run is the bookkeeping rollup for one agent invocation: the prompt,
the plan the agent declared (via the `update_plan` MCP tool), how far
through it the agent has gotten, and the final status + error. The UI
shows "Aki Sales is on step 3 of 5" by reading from here.

Routes:
  GET    /agents/{id}/current-run         → most recent non-completed run or 404
  GET    /agents/{id}/runs?limit=N        → newest-first run list
  POST   /agents/{id}/runs body: {prompt} → start a new run, dispatched async
  POST   /agents/{id}/runs/{run_id}/cancel → terminal-cancel a running row

Dispatch is fire-and-forget: POST /runs returns 202 with the run_id
immediately. The background task drives chat-completions and updates
the run row as it goes. Polling /current-run is the UI's way of
following progress.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import agent_runs as runs_mod
from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Agent


log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["runs"])


# ── helpers ────────────────────────────────────────────────────────────────


async def _resolve_agent_or_404(
    db: AsyncSession, principal: Principal, agent_id: UUID
) -> Agent:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return agent


# ── schemas ────────────────────────────────────────────────────────────────


class RunCreate(BaseModel):
    # 16k cap mirrors the system_prompt MAX in agents.py — same shape of
    # protection against runaway pastes.
    prompt: str = Field(min_length=1, max_length=16_000)


# ── routes ─────────────────────────────────────────────────────────────────


@router.get("/{agent_id}/current-run")
async def get_current_run(
    agent_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Most recent run with status='running' for this agent, or 404."""
    await _resolve_agent_or_404(db, principal, agent_id)
    run = await runs_mod.get_current_run(
        db, principal.organization_id, agent_id
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no current run")
    return runs_mod.to_wire(run)


@router.get("/{agent_id}/runs")
async def list_runs(
    agent_id: Annotated[UUID, Path()],
    limit: int = Query(20, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _resolve_agent_or_404(db, principal, agent_id)
    rows = await runs_mod.list_runs(
        db, principal.organization_id, agent_id, limit=limit
    )
    return [runs_mod.to_wire(r) for r in rows]


@router.post("/{agent_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    agent_id: Annotated[UUID, Path()],
    body: RunCreate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Create a run row + fire-and-forget dispatch. Returns the run_id so
    the caller can poll /current-run for progress."""
    agent = await _resolve_agent_or_404(db, principal, agent_id)

    run = await runs_mod.create_run(
        db,
        principal.organization_id,
        agent.id,
        body.prompt,
    )
    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="run.start",
        target=str(run.id),
        payload={"prompt_len": len(body.prompt), "trigger": "user"},
        agent_id=agent.id,
    )
    await db.commit()

    # Import here to avoid a startup-time circular: scheduler imports from
    # agent_runtime which (transitively, via routes/__init__.py via main.py)
    # imports the route modules. The lazy import keeps the import graph DAG.
    from app.scheduler import dispatch_run

    org_id = principal.organization_id
    asyncio.create_task(
        dispatch_run(org_id, agent.id, run.id, body.prompt, trigger="user")
    )

    return {
        "run_id": str(run.id),
        "status": "running",
        "agent_id": str(agent.id),
    }


@router.post("/{agent_id}/runs/{run_id}/cancel")
async def cancel_run(
    agent_id: Annotated[UUID, Path()],
    run_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Mark a run canceled. Idempotent: cancel-after-done is a no-op
    (returns the row in its terminal state).

    v1 cancel is cooperative: the dispatcher's background task notices
    a terminal status only at its next DB read. For chat completions
    that means it'll run to completion of the current LLM turn before
    stopping. A hard kill (cancel the httpx stream) is a v2 upgrade.
    """
    agent = await _resolve_agent_or_404(db, principal, agent_id)
    run = await runs_mod.complete(
        db,
        principal.organization_id,
        run_id,
        status="canceled",
    )
    if run is None or run.agent_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="run.cancel",
        target=str(run.id),
        payload={"prior_status": run.status},
        agent_id=agent.id,
    )
    await db.commit()
    await db.refresh(run)
    return runs_mod.to_wire(run)
