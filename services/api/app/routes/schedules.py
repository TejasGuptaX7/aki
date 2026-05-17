"""/agents/{id}/schedules — cron-driven agent invocations.

Each schedule fires a new agent_run with a fixed prompt on its cron
expression. APScheduler runs them in-process (see app/scheduler.py).

Routes:
  GET    /agents/{id}/schedules                  → list this agent's schedules
  POST   /agents/{id}/schedules body: {cron, prompt}
  PATCH  /agents/{id}/schedules/{schedule_id}    → update cron/prompt/enabled
  DELETE /agents/{id}/schedules/{schedule_id}

All cron strings are UTC and validated by APScheduler's CronTrigger
parser at POST/PATCH time so we never persist a string the scheduler
can't fire.
"""
from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID, uuid4

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scheduler
from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Agent, AgentSchedule


log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["schedules"])


# ── helpers ────────────────────────────────────────────────────────────────


def _validate_cron(s: str) -> str:
    try:
        CronTrigger.from_crontab(s, timezone="UTC")
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid cron expression: {e}"
        )
    return s


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


def _to_wire(s: AgentSchedule) -> dict:
    return {
        "id": str(s.id),
        "agent_id": str(s.agent_id),
        "cron": s.cron,
        "prompt": s.prompt,
        "enabled": s.enabled,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


# ── schemas ────────────────────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    cron: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=16_000)
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _check_cron(cls, v: str) -> str:
        return _validate_cron(v.strip())


class ScheduleUpdate(BaseModel):
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    prompt: str | None = Field(default=None, min_length=1, max_length=16_000)
    enabled: bool | None = None

    @field_validator("cron")
    @classmethod
    def _check_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_cron(v.strip())


# ── routes ─────────────────────────────────────────────────────────────────


@router.get("/{agent_id}/schedules")
async def list_schedules(
    agent_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _resolve_agent_or_404(db, principal, agent_id)
    rows = (
        await db.execute(
            select(AgentSchedule)
            .where(
                AgentSchedule.organization_id == principal.organization_id,
                AgentSchedule.agent_id == agent_id,
            )
            .order_by(AgentSchedule.created_at.desc())
        )
    ).scalars().all()
    return [_to_wire(s) for s in rows]


@router.post("/{agent_id}/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    agent_id: Annotated[UUID, Path()],
    body: ScheduleCreate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    agent = await _resolve_agent_or_404(db, principal, agent_id)

    row = AgentSchedule(
        id=uuid4(),
        organization_id=principal.organization_id,
        agent_id=agent.id,
        cron=body.cron,
        prompt=body.prompt,
        enabled=body.enabled,
    )
    db.add(row)
    await db.flush()

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="schedule.create",
        target=str(row.id),
        payload={"cron": body.cron, "enabled": body.enabled},
        agent_id=agent.id,
    )
    await db.commit()
    await db.refresh(row)

    # Register with the in-process scheduler AFTER the DB row is committed,
    # so the cron callback can read it back.
    scheduler.add_schedule(row)
    return _to_wire(row)


@router.patch("/{agent_id}/schedules/{schedule_id}")
async def update_schedule(
    agent_id: Annotated[UUID, Path()],
    schedule_id: Annotated[UUID, Path()],
    body: ScheduleUpdate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _resolve_agent_or_404(db, principal, agent_id)
    row = await db.scalar(
        select(AgentSchedule).where(
            AgentSchedule.id == schedule_id,
            AgentSchedule.organization_id == principal.organization_id,
            AgentSchedule.agent_id == agent_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")

    changed: dict[str, object] = {}
    if body.cron is not None and body.cron != row.cron:
        row.cron = body.cron
        changed["cron"] = body.cron
    if body.prompt is not None and body.prompt != row.prompt:
        row.prompt = body.prompt
        changed["prompt_len"] = len(body.prompt)
    if body.enabled is not None and body.enabled != row.enabled:
        row.enabled = body.enabled
        changed["enabled"] = body.enabled

    if changed:
        await append_audit(
            db,
            principal.organization_id,
            actor=principal.user_id,
            action="schedule.update",
            target=str(row.id),
            payload=changed,
            agent_id=agent_id,
        )
        await db.commit()
        await db.refresh(row)
        scheduler.replace_schedule(row)
    return _to_wire(row)


@router.delete(
    "/{agent_id}/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule(
    agent_id: Annotated[UUID, Path()],
    schedule_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    await _resolve_agent_or_404(db, principal, agent_id)
    row = await db.scalar(
        select(AgentSchedule).where(
            AgentSchedule.id == schedule_id,
            AgentSchedule.organization_id == principal.organization_id,
            AgentSchedule.agent_id == agent_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")

    await db.delete(row)
    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="schedule.delete",
        target=str(schedule_id),
        payload={"cron": row.cron},
        agent_id=agent_id,
    )
    await db.commit()
    scheduler.remove_schedule(schedule_id)
