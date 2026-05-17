"""Per-agent memory + identity (the Brain tab backend).

Hermes 0.13 stores three things in the per-agent profile workspace:
  - SOUL.md     — agent identity/personality (human-only edits in Hermes
                  convention; we honor that — never overwritten by the agent)
  - MEMORY.md   — org-wide memory (org_entries in our wire shape).
                  Lazily created by Hermes on first agent write.
                  §-delimited entries.
                  Hermes cap: ~2,200 chars total. We surface the count.
  - USER.md     — per-user persona context (user_entries). Same §-delimited
                  format. Cap: ~1,375 chars. v1 ignores the "per-user"
                  distinction since memberships isn't in yet — everything
                  in USER.md is per-org. We expose it as user_entries so
                  the frontend's data shape doesn't change when we add
                  memberships later.

Editing UX caveats baked in:
  - Mid-session edits don't take effect until the agent's NEXT session.
    The PATCH/POST/DELETE responses include `applies_at: "next_session"`
    so the frontend can show the "Aki will pick this up next run" banner.
  - Entries are identified by short content hash (first 16 chars of
    sha256). Stable as long as content doesn't change.
  - On write we validate the §-delimited shape so the agent's next
    `replace`/`remove` tool call doesn't get confused by a malformed
    entry.

File path: `${HERMES_DATA_DIR}/<org_id>/agents/<agent_id>/profiles/<agent_id>/`
matches what `_seed_agent_workspace` creates in agent_runtime.py.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import Principal
from app.config import get_settings
from app.middleware import get_principal, get_session
from app.models import Agent


router = APIRouter(prefix="/agents", tags=["memory"])


# Hermes's own caps from its docs.
MEMORY_MD_MAX = 2_200
USER_MD_MAX = 1_375
SOUL_MD_MAX = 16_000   # human-edited; we set a generous limit


# ── File path helpers ──────────────────────────────────────────────────────


def _profile_dir(org_id: UUID, agent_id: UUID) -> Path:
    s = get_settings()
    p = (
        Path(s.hermes_data_dir).expanduser()
        / str(org_id)
        / "agents"
        / str(agent_id)
        / "profiles"
        / str(agent_id)
    )
    return p


def _read_or_empty(p: Path) -> str:
    try:
        return p.read_text() if p.exists() else ""
    except Exception:
        return ""


def _write_atomic(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content)
    tmp.chmod(0o600)
    tmp.replace(p)


# ── Entry parsing ──────────────────────────────────────────────────────────


def _entry_id(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def _parse_entries(text: str) -> list[dict]:
    """Split a §-delimited memory file into individual entries with stable
    content-hash ids. Empty entries collapse out."""
    if not text:
        return []
    return [
        {"id": _entry_id(p), "text": p.strip()}
        for p in text.split("§")
        if p.strip()
    ]


def _format_entries(entries: list[str]) -> str:
    """Join entries with " § " separator + trailing newline. Matches how
    Hermes writes them back so the agent's own replace/remove can target
    them with substring matching."""
    if not entries:
        return ""
    joined = " § ".join(e.strip() for e in entries if e.strip())
    return joined + "\n"


# ── Authn + agent lookup ───────────────────────────────────────────────────


async def _require_agent(
    db: AsyncSession, principal: Principal, agent_id: UUID
) -> Agent:
    a = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return a


# ── Pydantic ───────────────────────────────────────────────────────────────


class SoulUpdate(BaseModel):
    content: str = Field(default="", max_length=SOUL_MD_MAX)


class EntryCreate(BaseModel):
    scope: str = Field(pattern="^(org|user)$")
    text: str = Field(min_length=1, max_length=MEMORY_MD_MAX)


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/{agent_id}/memory")
async def get_memory(
    agent_id: Annotated[UUID, PathParam()],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    agent = await _require_agent(db, principal, agent_id)
    pdir = _profile_dir(agent.organization_id, agent.id)

    soul = _read_or_empty(pdir / "SOUL.md")
    memory_raw = _read_or_empty(pdir / "MEMORY.md")
    user_raw = _read_or_empty(pdir / "USER.md")

    return {
        "agent_id": str(agent.id),
        "soul": {
            "content": soul,
            "chars": len(soul),
            "cap": SOUL_MD_MAX,
        },
        "org_entries": _parse_entries(memory_raw),
        "user_entries": _parse_entries(user_raw),
        "limits": {
            "memory_md_max": MEMORY_MD_MAX,
            "user_md_max": USER_MD_MAX,
            "memory_md_used": len(memory_raw),
            "user_md_used": len(user_raw),
        },
        # FE renders a banner with this so users don't expect live behavior.
        "applies_at": "next_session",
    }


@router.patch("/{agent_id}/memory/soul")
async def patch_soul(
    agent_id: Annotated[UUID, PathParam()],
    body: SoulUpdate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    agent = await _require_agent(db, principal, agent_id)
    pdir = _profile_dir(agent.organization_id, agent.id)
    _write_atomic(pdir / "SOUL.md", body.content)
    # Also write to the HERMES_HOME-level SOUL.md — Hermes reads from
    # one or the other depending on context; writing both keeps them
    # in sync regardless of which Hermes picks up.
    home_soul = pdir.parent.parent / "SOUL.md"
    try:
        _write_atomic(home_soul, body.content)
    except Exception:
        pass

    await append_audit(
        db,
        agent.organization_id,
        actor=principal.user_id,
        action="memory.soul.update",
        target=str(agent.id),
        payload={"chars": len(body.content)},
        agent_id=agent.id,
    )
    await db.commit()
    return {"ok": True, "applies_at": "next_session"}


@router.post(
    "/{agent_id}/memory/entry",
    status_code=status.HTTP_201_CREATED,
)
async def add_entry(
    agent_id: Annotated[UUID, PathParam()],
    body: EntryCreate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    agent = await _require_agent(db, principal, agent_id)
    pdir = _profile_dir(agent.organization_id, agent.id)

    path = pdir / ("MEMORY.md" if body.scope == "org" else "USER.md")
    cap = MEMORY_MD_MAX if body.scope == "org" else USER_MD_MAX

    existing = _read_or_empty(path)
    entries = [e["text"] for e in _parse_entries(existing)]
    entries.append(body.text.strip())
    new_text = _format_entries(entries)
    if len(new_text) > cap:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {
                "error": "cap_exceeded",
                "cap": cap,
                "would_be": len(new_text),
                "scope": body.scope,
                "message": (
                    "This entry would push memory over the cap. Remove or "
                    "shorten an existing entry first."
                ),
            },
        )
    _write_atomic(path, new_text)

    new_entry_id = _entry_id(body.text)
    await append_audit(
        db,
        agent.organization_id,
        actor=principal.user_id,
        action="memory.entry.add",
        target=str(agent.id),
        payload={"scope": body.scope, "entry_id": new_entry_id,
                 "chars": len(body.text)},
        agent_id=agent.id,
    )
    await db.commit()

    return {
        "id": new_entry_id,
        "text": body.text.strip(),
        "scope": body.scope,
        "applies_at": "next_session",
    }


@router.delete(
    "/{agent_id}/memory/entry/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entry(
    agent_id: Annotated[UUID, PathParam()],
    entry_id: Annotated[str, PathParam(min_length=8, max_length=64)],
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    agent = await _require_agent(db, principal, agent_id)
    pdir = _profile_dir(agent.organization_id, agent.id)

    # Search both files; first match wins. Entry IDs are content-hash so
    # they're unique across both scopes in practice.
    for scope, fname in (("org", "MEMORY.md"), ("user", "USER.md")):
        path = pdir / fname
        existing = _read_or_empty(path)
        entries = _parse_entries(existing)
        kept = [e["text"] for e in entries if e["id"] != entry_id]
        if len(kept) != len(entries):
            _write_atomic(path, _format_entries(kept))
            await append_audit(
                db,
                agent.organization_id,
                actor=principal.user_id,
                action="memory.entry.delete",
                target=str(agent.id),
                payload={"scope": scope, "entry_id": entry_id},
                agent_id=agent.id,
            )
            await db.commit()
            return
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        f"no entry with id={entry_id} found in either scope",
    )
