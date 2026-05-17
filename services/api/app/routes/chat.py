"""OpenAI-compatible chat completions proxy.

POST /v1/chat/completions →
  1. RBAC stub (returns silently for v1; layered later when memberships land)
  2. ensure_running(org_id) — cold-starts the per-org Hermes container if needed
  3. write a chat.start audit row
  4. forward request body to Hermes' OpenAI-compat API with the per-org bearer
  5. stream the response straight back, AND inline-tap the SSE stream:
     - each `event: hermes.tool.progress` payload becomes a chat.tool_call audit row
     - the final OpenAI-shape chunk's `usage` becomes a chat.complete audit row
  6. write all collected audit rows in one transaction after the stream closes

Hermes' streaming response is OpenAI-compatible chunks interleaved with custom
`event: hermes.*` lines (see Hermes 0.13 gateway code). We pass every byte to
the client untouched and parse a side-buffer for audit purposes.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import HermesProcess, ensure_running
from app.audit import append_audit
from app.auth import Principal
from app.config import get_settings
from app.db import session_for_org
from app.middleware import get_principal, get_session
from app.pricing import estimate_cost_usd


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


AKI_SYSTEM_PROMPT = """\
You are Aki, an agent embedded in a company. Operate against the user's
connected tools (Composio, Browser Use) via MCP.

Slack:
- ALWAYS use the `slackbot` toolkit when posting to Slack, never `slack`.
  `slack` posts as the human; `slackbot` posts as the workspace bot. Even
  if both seem available, prefer slackbot. If only `slack` is available,
  tell the user to install the bot via the Connect page rather than
  posting as them.
- Bots can only post in channels they've been invited to. If a post
  fails with `not_in_channel`, ask the user to /invite the bot first.

Gmail and other Composio tools: act on behalf of the user as expected.

Destructive actions (send email, post message, write to a database,
file/event creation): briefly confirm intent before executing if the
user's request is ambiguous. For clearly-requested actions, just do them.

Cite sources for any factual claims pulled from a tool.
"""


async def _rbac_check(principal: Principal, action: str) -> None:
    """v1 stub. Replace with real check when memberships table lands."""
    return None


def _parse_sse_blocks(chunk_buf: str):
    """Yield (event_name, data_str) for each complete SSE block in `chunk_buf`.
    Returns the unparsed tail to keep buffering. SSE blocks are separated by
    a blank line; within a block, lines starting with `event:` or `data:` are
    accumulated."""
    blocks: list[tuple[str | None, str]] = []
    pos = 0
    while True:
        sep = chunk_buf.find("\n\n", pos)
        if sep == -1:
            return blocks, chunk_buf[pos:]
        block = chunk_buf[pos:sep]
        pos = sep + 2
        event = None
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            blocks.append((event, "\n".join(data_lines)))


async def _flush_audit(
    org_id, actor: str, container_id: str,
    tool_events: list[dict], final_usage: dict | None,
    duration_ms: int,
) -> None:
    """Open a fresh session and write tool_call + chat.complete rows.

    The handler's `db` session is closed by the time the stream finishes —
    StreamingResponse runs the generator after the route returns. We open our
    own session so audit writes still happen.
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
                )
            except Exception:
                log.exception("audit chat.tool_call failed for evt=%s", evt)

        try:
            usage = final_usage or {}
            model_name = get_settings().hermes_model_name
            cost_usd = estimate_cost_usd(
                model_name,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            ) if usage else 0.0
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
            )
        except Exception:
            log.exception("audit chat.complete failed")
        await db.commit()


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    await _rbac_check(principal, "chat.send")

    body = await request.body()
    # Inject Aki's system prompt at the front of the messages list so the
    # agent has standing guidance (bot identity for Slack, ask before
    # destructive actions, etc.). We rewrite the request body in place.
    try:
        import json as _json
        body_dict = _json.loads(body) if body else {}
        msgs = body_dict.get("messages") or []
        has_system = any((m or {}).get("role") == "system" for m in msgs)
        if not has_system:
            body_dict["messages"] = [{"role": "system", "content": AKI_SYSTEM_PROMPT}, *msgs]
            body = _json.dumps(body_dict).encode("utf-8")
    except Exception:
        log.exception("system-prompt injection failed; passing body through")

    proc: HermesProcess = await ensure_running(db, principal.organization_id)

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="chat.start",
        target=proc.container_id,
        payload={"bytes": len(body)},
    )
    await db.commit()

    headers = {
        "Authorization": f"Bearer {proc.api_key}",
        "Content-Type": request.headers.get("Content-Type", "application/json"),
    }

    org_id = principal.organization_id
    actor = principal.user_id
    container_id = proc.container_id
    started = time.monotonic()

    async def stream():
        tool_events: list[dict] = []
        final_usage: dict | None = None
        tail = ""

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as c:
                async with c.stream(
                    "POST",
                    f"{proc.base_url}/v1/chat/completions",
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
                                # Last OpenAI-shape chunk carries usage.
                                final_usage = obj["usage"]
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await _flush_audit(org_id, actor, container_id, tool_events, final_usage, duration_ms)
            except Exception:
                log.exception("audit flush failed")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "X-Aki-Org-Id": str(principal.organization_id),
            "X-Aki-Container-Id": proc.container_id[:12],
            "Cache-Control": "no-cache",
        },
    )
