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
from app.consent import Tier, tier_for_tool
from app.db import session_for_org
from app.middleware import get_principal, get_session
from app.models import Agent, ChatMessage
from app.pricing import estimate_cost_usd
from app.rate_limits import Kind as RLKind, enforce_daily_cap, record_usage


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


def _last_user_message(body_dict: dict) -> str | None:
    """Pluck the final user-role message from the request's `messages` array,
    if any. That's the new turn we want to persist; everything before it is
    history the frontend re-sent for context."""
    msgs = (body_dict or {}).get("messages") or []
    for m in reversed(msgs):
        if (m or {}).get("role") == "user":
            content = m.get("content")
            # OpenAI allows content as a list of content-parts for vision;
            # join the text parts for chat-history display.
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text"]
                return "".join(parts) or None
            return None
    return None


async def _flush_audit(
    org_id: UUID,
    agent_id: UUID,
    actor: str,
    container_id: str,
    tool_events: list[dict],
    final_usage: dict | None,
    duration_ms: int,
    assistant_content: str,
) -> None:
    """Open a fresh session and write tool_call + chat.complete rows.

    The handler's `db` session is closed by the time the stream finishes —
    StreamingResponse runs the generator after the route returns. We open
    our own session so audit writes still happen.
    """
    async with session_for_org(org_id) as db:
        for evt in tool_events:
            try:
                tool_name = evt.get("tool") or ""
                tier = tier_for_tool(tool_name)
                payload = {
                    "tool": tool_name,
                    "status": evt.get("status"),
                    "label": evt.get("label"),
                    "container_id": container_id,
                    "tier": int(tier),
                }
                if tier is Tier.FORBID:
                    # v1: log loudly so the operator notices. Real enforcement
                    # (MCP-layer interception that refuses these tools) is on
                    # the v2 roadmap; for now we rely on OAuth scoping +
                    # system prompt to prevent reaching this branch.
                    log.error(
                        "SECURITY: tier-3 (forbid) tool called org=%s agent=%s tool=%s",
                        org_id, agent_id, tool_name,
                    )
                    payload["security_alert"] = True
                await append_audit(
                    db,
                    org_id,
                    actor=actor,
                    action="chat.tool_call",
                    target=evt.get("toolCallId") or evt.get("tool_call_id") or "",
                    payload=payload,
                    agent_id=agent_id,
                )
            except Exception:
                log.exception("audit chat.tool_call failed for evt=%s", evt)

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
        try:
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

        # Record daily-cap usage. 1 action per chat turn, llm spend in cents
        # rounded up (better to over-count than under-count for abuse defense).
        try:
            await record_usage(db, org_id, RLKind.ACTIONS, 1)
            cost_cents = max(1, int(round(cost_usd * 100))) if cost_usd > 0 else 0
            if cost_cents:
                await record_usage(db, org_id, RLKind.LLM_CENTS, cost_cents)
        except Exception:
            log.exception("rate_limits record_usage failed")

        # Persist the assistant's response for chat-history GETs. Tool-call
        # contents stay in the audit log; this table holds only the visible
        # text the user saw. Empty content (agent ran tools, said nothing)
        # is still persisted so refresh-history shows that the turn happened.
        try:
            db.add(
                ChatMessage(
                    organization_id=org_id,
                    agent_id=agent_id,
                    role="assistant",
                    content=assistant_content or "",
                )
            )
        except Exception:
            log.exception("chat_messages assistant persist failed")

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

    # Cap check before any expensive work (cold-starting a container costs
    # ~10s of compute; refusing here saves that for abusive orgs).
    await enforce_daily_cap(db, principal.organization_id, RLKind.ACTIONS)
    await enforce_daily_cap(db, principal.organization_id, RLKind.LLM_CENTS)

    body = await request.body()
    body = _inject_system_prompt(body, agent.system_prompt)

    # Persist the user's new turn so chat history GETs reflect what was
    # asked even if the chat fails mid-stream. The history-aware messages
    # array the frontend sent us is the source; we pluck the LAST user
    # role entry as the new turn.
    try:
        body_dict = json.loads(body) if body else {}
    except Exception:
        body_dict = {}
    user_text = _last_user_message(body_dict)
    if user_text:
        db.add(
            ChatMessage(
                organization_id=principal.organization_id,
                agent_id=agent.id,
                role="user",
                content=user_text,
            )
        )

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
        assistant_parts: list[str] = []
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
                            elif isinstance(obj, dict):
                                if "usage" in obj:
                                    final_usage = obj["usage"]
                                # Accumulate visible content for the
                                # persisted assistant message. OpenAI shape:
                                # choices[0].delta.content is a string per
                                # chunk; tool-call deltas live elsewhere
                                # and are intentionally NOT captured here.
                                choices = obj.get("choices") or []
                                if choices:
                                    delta = (choices[0] or {}).get("delta") or {}
                                    piece = delta.get("content")
                                    if isinstance(piece, str) and piece:
                                        assistant_parts.append(piece)
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await _flush_audit(
                    org_id, agent.id, actor, container_id,
                    tool_events, final_usage, duration_ms,
                    "".join(assistant_parts),
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
