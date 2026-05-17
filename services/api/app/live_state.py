"""Ephemeral per-(org, agent) "currently doing" state for the Inspector Board.

The /agents/board endpoint shows tiles. Each tile wants to flash a status
pill + the agent's current action when the agent is actively in a chat
turn (not just "last seen 4 hours ago" from audit).

This module is a tiny in-memory writer/reader the chat route updates on
every SSE chunk it taps. The Inspector Board reads from it; absent
entries mean "not currently active" — the FE falls back to the audit-
derived last_action.

Why in-memory and not a DB column:
  - Updates happen 5-50x per chat turn (every tool call). DB writes would
    hammer Postgres + spam the audit log.
  - Information is intrinsically ephemeral — no value in persisting
    "currently calling gmail_send_message" past container hibernation.
  - On uvicorn restart, the state is gone. Acceptable: live agents
    re-populate on their next tool call within seconds; idle agents
    correctly report nothing.

When we go multi-worker, swap this dict for Redis with the same shape.
Same interface; one-line change in record_*/get_state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import UUID


# TTL after which an entry is considered stale. The chat route updates
# every few seconds during an active stream; we evict anything older
# than 90s so a crashed/cancelled chat doesn't leave a tile showing
# "still running" forever.
LIVE_TTL_S = 90.0


@dataclass
class _AgentLive:
    last_seen: float = field(default_factory=lambda: time.time())
    started_at: float = field(default_factory=lambda: time.time())
    current_step: str = ""              # short label of latest activity
    tool_calls_this_turn: int = 0


_STATE: dict[tuple[UUID, UUID], _AgentLive] = {}
_LOCK = Lock()


def record_turn_start(org_id: UUID, agent_id: UUID) -> None:
    """Called by chat route at chat.start. Resets per-turn counters
    and seeds the started_at clock."""
    now = time.time()
    with _LOCK:
        _STATE[(org_id, agent_id)] = _AgentLive(
            last_seen=now,
            started_at=now,
            current_step="thinking",
            tool_calls_this_turn=0,
        )


def record_tool_call(
    org_id: UUID,
    agent_id: UUID,
    tool_label: str,
) -> None:
    """Called by chat route's SSE tap on each `hermes.tool.progress` event."""
    now = time.time()
    with _LOCK:
        s = _STATE.get((org_id, agent_id))
        if s is None:
            s = _AgentLive(last_seen=now, started_at=now)
            _STATE[(org_id, agent_id)] = s
        s.last_seen = now
        s.current_step = (tool_label or "calling tool")[:80]
        s.tool_calls_this_turn += 1


def record_turn_complete(org_id: UUID, agent_id: UUID) -> None:
    """Called by chat route at chat.complete. Marks the entry as 'done'
    but keeps it around for a few seconds so the FE can render the
    completed state before it disappears."""
    with _LOCK:
        s = _STATE.get((org_id, agent_id))
        if s is not None:
            s.current_step = "done"
            s.last_seen = time.time()


def get_state(org_id: UUID, agent_id: UUID) -> dict[str, Any] | None:
    """Return a wire-shape dict for the FE, or None if no live data."""
    now = time.time()
    with _LOCK:
        s = _STATE.get((org_id, agent_id))
        if s is None:
            return None
        if now - s.last_seen > LIVE_TTL_S:
            _STATE.pop((org_id, agent_id), None)
            return None
        return {
            "is_active": s.current_step not in ("", "done"),
            "current_step": s.current_step,
            "started_at": s.started_at,
            "elapsed_s": round(now - s.started_at, 1),
            "tool_calls_this_turn": s.tool_calls_this_turn,
            "last_seen": s.last_seen,
        }


def sweep_expired() -> int:
    """Drop entries older than TTL. Returns count dropped. Cheap; safe
    to call from a periodic task or every read."""
    now = time.time()
    with _LOCK:
        expired = [
            k for k, v in _STATE.items()
            if now - v.last_seen > LIVE_TTL_S
        ]
        for k in expired:
            _STATE.pop(k, None)
        return len(expired)
