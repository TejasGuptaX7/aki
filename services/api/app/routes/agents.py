"""/agents — named, long-lived per-org agents.

Each agent is its own Hermes profile inside the org's container: own
system prompt, own memory namespace, own connections scope. See
`docs/architecture.md` §5 for the runtime model and §3 for the tenancy
boundary this lives inside.

Routes:
  POST   /agents                       create
  GET    /agents                       list (active first, then hibernated)
  GET    /agents/templates             list curated starter templates
  POST   /agents/from-template/{key}   create from a template
  GET    /agents/{id}                  detail (includes full system_prompt)
  PATCH  /agents/{id}                  update name / system_prompt
  DELETE /agents/{id}                  soft delete (status='deleted')
  GET    /agents/{id}/messages         chat history (chronological)

The slug is the URL- and Slack-mention-safe handle. Generated from name,
auto-disambiguated on collision (sales, sales-2, sales-3, …). Once set
it does NOT change on rename — slug is the stable identity, name is the
display label. Changing the slug would invalidate any '@aki-sales' DM in
flight, every audit row pointing at it by slug, etc.
"""
from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_templates import TEMPLATES, get_template, list_templates
from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Agent, ChatMessage


router = APIRouter(prefix="/agents", tags=["agents"])


# Roughly the brief size at which a system prompt stops being a brief
# and becomes a wiki. Cheap protection against runaway pasting; raise
# later if a customer asks.
MAX_SYSTEM_PROMPT_CHARS = 8_000

DEFAULT_SYSTEM_PROMPT = """\
You are {name}, an agent embedded inside a company. Operate against the tools
the company has connected. Be honest about what you did, cite sources.

CONSENT — three tiers:

  TIER 1 (auto): Read operations, search, lookup, navigation. Just do them
                 and report the results.

  TIER 2 (ASK FIRST): Anything externally visible or irreversible — sending
                      email to outside parties, posting in public channels,
                      signing up for new accounts, deleting records, inviting
                      users. Before each such action, call the `request_approval`
                      tool with:
                          kind:    short category, e.g. "email.send"
                          tool:    the tool you're about to use, e.g. "gmail_send_message"
                          args:    the args you'd pass to that tool, verbatim
                          summary: one-line human description
                      The call blocks until the user approves (returns
                      {approved: true}) or denies (returns {approved: false}).
                      Only proceed if approved. If denied or timed out
                      ({status: "pending_timeout"}), tell the user the request
                      is waiting in their approvals inbox and stop.

  TIER 3 (NEVER): Anything that moves money. No payments, no card entries,
                  no purchase confirmations, no financial commitments. Refuse
                  with a clear explanation if asked.

Cite sources for any factual claims pulled from a tool. When a long task
finishes, summarize what you did and which tools you used."""


def _slugify(name: str) -> str:
    """Lowercase, alnum + hyphens, max 64 chars. Always returns a non-empty
    string; falls back to 'agent' for pathological inputs."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:64] or "agent")


async def _unique_slug(db: AsyncSession, org_id: UUID, base: str) -> str:
    """Append -2, -3, … until we find a free slug. O(n) worst case but n
    here is the count of name collisions within one org — single digits
    in practice."""
    candidate = base
    i = 2
    while True:
        existing = await db.scalar(
            select(Agent.id).where(
                Agent.organization_id == org_id,
                Agent.slug == candidate,
            )
        )
        if existing is None:
            return candidate
        suffix = f"-{i}"
        candidate = f"{base[: 64 - len(suffix)]}{suffix}"
        i += 1


# ── Pydantic schemas ────────────────────────────────────────────────────────


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_CHARS)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_CHARS)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()


def _summary(a: Agent) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "status": a.status,
        "created_at": a.created_at.isoformat(),
        "hibernated_at": a.hibernated_at.isoformat() if a.hibernated_at else None,
    }


def _detail(a: Agent) -> dict:
    return {
        **_summary(a),
        "system_prompt": a.system_prompt,
        "browser_profile_id": a.browser_profile_id,
        "updated_at": a.updated_at.isoformat(),
    }


# ── routes ──────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    base = _slugify(body.name)
    slug = await _unique_slug(db, principal.organization_id, base)

    prompt = body.system_prompt
    if not prompt:
        prompt = DEFAULT_SYSTEM_PROMPT.format(name=body.name.strip())

    agent = Agent(
        id=uuid4(),
        organization_id=principal.organization_id,
        name=body.name.strip(),
        slug=slug,
        system_prompt=prompt,
        status="active",
    )
    db.add(agent)
    await db.flush()

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="agent.create",
        target=str(agent.id),
        payload={"name": agent.name, "slug": agent.slug},
        agent_id=agent.id,
    )
    await db.commit()
    await db.refresh(agent)
    return _detail(agent)


@router.get("")
async def list_agents(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await db.execute(
            select(Agent)
            .where(
                Agent.organization_id == principal.organization_id,
                Agent.status != "deleted",
            )
            .order_by(
                # active first, then hibernated; within each, newest first
                func.coalesce(Agent.status, "").asc(),
                Agent.created_at.desc(),
            )
        )
    ).scalars().all()
    return [_summary(a) for a in rows]


# ── Templates (must be registered BEFORE /{agent_id} so FastAPI doesn't
#    try to parse "templates" or "from-template" as a UUID) ────────────────


@router.get("/templates")
async def list_agent_templates(
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    return list_templates()


class FromTemplateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()


@router.post("/from-template/{template_key}", status_code=status.HTTP_201_CREATED)
async def create_from_template(
    template_key: Annotated[str, Path(min_length=1, max_length=64)],
    body: FromTemplateBody | None = None,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    tmpl = get_template(template_key)
    if tmpl is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no template '{template_key}'; see GET /agents/templates",
        )

    name = (body.name if body and body.name else tmpl["name"])
    base = _slugify(name)
    slug = await _unique_slug(db, principal.organization_id, base)

    agent = Agent(
        id=uuid4(),
        organization_id=principal.organization_id,
        name=name,
        slug=slug,
        system_prompt=tmpl["system_prompt"],
        status="active",
    )
    db.add(agent)
    await db.flush()
    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="agent.create_from_template",
        target=str(agent.id),
        payload={
            "template_key": tmpl["key"],
            "name": agent.name,
            "slug": agent.slug,
        },
        agent_id=agent.id,
    )
    await db.commit()
    await db.refresh(agent)
    return _detail(agent)


# ── Per-agent sub-resources ────────────────────────────────────────────────


@router.get("/{agent_id}/messages")
async def list_chat_messages(
    agent_id: Annotated[UUID, Path()],
    limit: int = Query(200, ge=1, le=1000),
    before_id: int | None = Query(
        None, description="paginate older — return id < before_id"
    ),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Chat history for one agent, newest-first by id (the FE reverses
    for chronological display). Soft-deleted agents still expose their
    history so audits aren't lost."""
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    q = select(ChatMessage).where(
        ChatMessage.organization_id == principal.organization_id,
        ChatMessage.agent_id == agent_id,
    )
    if before_id is not None:
        q = q.where(ChatMessage.id < before_id)
    q = q.order_by(ChatMessage.id.desc()).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return _detail(agent)


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: Annotated[UUID, Path()],
    body: AgentUpdate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    changed: dict[str, object] = {}
    if body.name is not None and body.name.strip() != agent.name:
        agent.name = body.name.strip()
        changed["name"] = agent.name
        # NOTE: slug intentionally unchanged on rename. See module docstring.
    if body.system_prompt is not None and body.system_prompt != agent.system_prompt:
        agent.system_prompt = body.system_prompt
        changed["system_prompt_len"] = len(body.system_prompt)

    if changed:
        await append_audit(
            db,
            principal.organization_id,
            actor=principal.user_id,
            action="agent.update",
            target=str(agent.id),
            payload=changed,
            agent_id=agent.id,
        )
        await db.commit()
        await db.refresh(agent)
    return _detail(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: Annotated[UUID, Path()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    # Refuse to delete the last active agent — an org without any agent is
    # an org that can't chat, and "I deleted Aki" is a worse UX than the
    # 409 we return here.
    active_count = await db.scalar(
        select(func.count(Agent.id)).where(
            Agent.organization_id == principal.organization_id,
            Agent.status == "active",
        )
    )
    if agent.status == "active" and (active_count or 0) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cannot delete the last active agent; create another first",
        )

    agent.status = "deleted"
    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="agent.delete",
        target=str(agent.id),
        payload={"name": agent.name, "slug": agent.slug},
        agent_id=agent.id,
    )
    await db.commit()
