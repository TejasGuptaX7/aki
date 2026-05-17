"""OpenAI-compatible chat completions proxy, agent-scoped.

POST /v1/chat/completions →
  1. RBAC stub (no-op for v1; layered later when memberships land)
  2. resolve X-Aki-Agent-Id → Agent row; reject if missing / wrong org
  3. ensure_agent_loaded — cold-starts the per-org container if needed,
     loads the agent's Hermes profile if not already in the supervisor
  4. inject the agent's system_prompt as a system message (only if the
     incoming request has no system message of its own)
  5. forward to the supervisor with Bearer = supervisor API key + the
     X-Aki-Agent-Id header that the supervisor uses for routing
  6. stream response back AND inline-tap SSE for audit:
     - `event: hermes.tool.progress` → chat.tool_call audit row
     - final OpenAI chunk's `usage` → chat.complete audit row
  7. flush audit rows in their own session after the stream closes

The supervisor inside the container handles per-profile routing; from our
perspective there's still one URL per org. The agent_id only matters in
the header.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import OrgContainer, ensure_agent_loaded
from app.audit import append_audit
from app.auth import Principal
from app.config import get_settings
from app.db import session_for_org
from app.middleware import get_principal, get_session
from app.models import Agent
from app.pricing import estimate_cost_usd


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


async def _rbac_check(principal: Principal, action: str) -> None:
    """v1 stub. Replace with real check when memberships table lands."""
    return None


def _parse_sse_blocks(chunk_buf: str):
    """Yield (event_name, data_str) for each complete SSE block. Returns
    the unparsed tail to keep buffering."""
    blocks: list[tuple[str | None, str]] = []
    pos = 0
    while True:
        sep = chunk_buf.find("\n\n", pos)
        if sep == -1:
            return blocks, chunk_buf[pos:]
        block = chunk_buf[pos:sep]
        pos = sep + 2
        event = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            blocks.append((event, "\n".join(data_lines)))


async def _flush_audit(
    org_id: UUID,
    agent_id: UUID,
    actor: str,
    container_id: str,
    tool_events: list[dict],
    final_usage: dict | None,
    duration_ms: int,
) -> None:
    """Open a fresh session and write tool_call + chat.complete rows.

    The handler's `db` session is closed by the time the stream finishes —
    StreamingResponse runs the generator after the route returns. We open
    our own session so audit writes still happen.
    """
    async with session_for_org(org_id) as db:
        for evt in tool_events:
            try:
                await append_audit(
                    db,
                    org_id,
                    actor=actor,
                    action="chat.tool_call",
                    target=evt.get("toolCallId") or evt.get("tool_call_id") or "",
                    payload={
                        "tool": evt.get("tool"),
                        "status": evt.get("status"),
                        "label": evt.get("label"),
                        "container_id": container_id,
                    },
                    agent_id=agent_id,
                )
            except Exception:
                log.exception("audit chat.tool_call failed for evt=%s", evt)

        try:
            usage = final_usage or {}
            model_name = get_settings().hermes_model_name
            cost_usd = (
                estimate_cost_usd(
                    model_name,
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                )
                if usage
                else 0.0
            )
            await append_audit(
                db,
                org_id,
                actor=actor,
                action="chat.complete",
                target=container_id,
                payload={
                    "duration_ms": duration_ms,
                    "usage": usage,
                    "tool_calls": len(tool_events),
                    "model": model_name,
                    "cost_usd": cost_usd,
                },
                agent_id=agent_id,
            )
        except Exception:
            log.exception("audit chat.complete failed")
        await db.commit()


def _inject_system_prompt(body_bytes: bytes, prompt: str) -> bytes:
    """Prepend `prompt` as a system message only if the request has no
    system message. Returns the (possibly rewritten) body. Falls back to
    the original body on any error — chat must not be blocked by a parse
    failure."""
    if not prompt:
        return body_bytes
    try:
        body = json.loads(body_bytes) if body_bytes else {}
        msgs = body.get("messages") or []
        if any((m or {}).get("role") == "system" for m in msgs):
            return body_bytes
        body["messages"] = [{"role": "system", "content": prompt}, *msgs]
        return json.dumps(body).encode("utf-8")
    except Exception:
        log.exception("system-prompt injection failed; passing body through")
        return body_bytes


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    x_aki_agent_id: str = Header(..., alias="X-Aki-Agent-Id"),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    await _rbac_check(principal, "chat.send")

    try:
        agent_id = UUID(x_aki_agent_id)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "X-Aki-Agent-Id must be a valid UUID",
        )

    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == principal.organization_id,
        )
    )
    if agent is None or agent.status == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    if agent.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"agent status={agent.status}; cannot chat",
        )

    body = await request.body()
    body = _inject_system_prompt(body, agent.system_prompt)

    container: OrgContainer = await ensure_agent_loaded(
        db, principal.organization_id, agent.id
    )

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="chat.start",
        target=container.container_id,
        payload={"bytes": len(body)},
        agent_id=agent.id,
    )
    await db.commit()

    headers = {
        "Authorization": f"Bearer {container.supervisor_api_key}",
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "X-Aki-Agent-Id": str(agent.id),
    }

    org_id = principal.organization_id
    actor = principal.user_id
    container_id = container.container_id
    started = time.monotonic()

    async def stream():
        tool_events: list[dict] = []
        final_usage: dict | None = None
        tail = ""

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(600.0, connect=10.0)
            ) as c:
                async with c.stream(
                    "POST",
                    f"{container.base_url}/v1/chat/completions",
                    content=body,
                    headers=headers,
                ) as upstream:
                    async for raw in upstream.aiter_bytes():
                        yield raw
                        try:
                            tail += raw.decode("utf-8", errors="replace")
                        except Exception:
                            continue
                        blocks, tail = _parse_sse_blocks(tail)
                        for event, data in blocks:
                            if data == "[DONE]":
                                continue
                            try:
                                obj: Any = json.loads(data)
                            except Exception:
                                continue
                            if event and event.startswith("hermes.tool"):
                                tool_events.append(obj)
                            elif isinstance(obj, dict) and "usage" in obj:
                                final_usage = obj["usage"]
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await _flush_audit(
                    org_id, agent.id, actor, container_id,
                    tool_events, final_usage, duration_ms,
                )
            except Exception:
                log.exception("audit flush failed")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "X-Aki-Org-Id": str(principal.organization_id),
            "X-Aki-Agent-Id": str(agent.id),
            "X-Aki-Container-Id": container.container_id[:12],
            "Cache-Control": "no-cache",
        },
    )
