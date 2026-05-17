"""Hash-chained audit log writer.

The audit_log table is UPDATE/DELETE-blocked at the DB level (see
alembic/versions/0001_initial.py). Each row's `content_hash` is sha256 over a
canonical JSON encoding of the row's content + `prev_hash`. Verifying the chain
later means walking from row 1 forward and recomputing each hash.

Per-org serialization is enforced with a transaction-scoped advisory lock so
concurrent inserts can't race and pick the same prev_hash.

`agent_id` is part of the row but NOT part of the hash input — historically
audit rows existed without it (Phase 2a–2c), and changing the hash schema
retroactively would break chain verification on any existing row. New rows
keep the original hash shape; agent_id is queryable metadata only.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(
    org_id: UUID,
    actor: str,
    action: str,
    target: str | None,
    payload: dict[str, Any],
    prev_hash: str | None,
) -> str:
    body = _canonical(
        {
            "org": str(org_id),
            "actor": actor,
            "action": action,
            "target": target,
            "payload": payload,
            "prev": prev_hash,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


async def append_audit(
    db: AsyncSession,
    org_id: UUID,
    actor: str,
    action: str,
    target: str | None = None,
    payload: dict[str, Any] | None = None,
    *,
    agent_id: UUID | None = None,
) -> AuditLog:
    """Append one audit row. Caller is responsible for the surrounding
    transaction (commit/rollback). RLS GUC must already be set for `org_id`.

    `agent_id` should be set for any event scoped to a specific agent
    (chat.*, approval.*, browser.*) and left NULL for org-level events
    (org.*, oauth.*, webhook.*).
    """
    payload = payload or {}

    # Advisory lock keyed on org so concurrent appends serialize.
    # hashtext gives us a stable int from the uuid string.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"audit:{org_id}"},
    )

    prev = (
        await db.execute(
            select(AuditLog.content_hash)
            .where(AuditLog.organization_id == org_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    content_hash = _hash(org_id, actor, action, target, payload, prev)

    row = AuditLog(
        organization_id=org_id,
        agent_id=agent_id,
        actor=actor,
        action=action,
        target=target,
        payload=payload,
        content_hash=content_hash,
        prev_hash=prev,
    )
    db.add(row)
    await db.flush()
    return row
