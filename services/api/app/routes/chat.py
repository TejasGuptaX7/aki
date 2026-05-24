"""OpenAI-compatible chat completions proxy.

POST /v1/chat/completions →
  1. RBAC check (chat:create permission + department membership)
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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import HermesProcess, ensure_running
from app.audit import append_audit
from app.auth import Principal
from app.brain import hydrate_messages
from app.config import get_settings
from app.cost_caps import enforce_spend_cap
from app.db import session_for_org
from app.limits import limiter, org_limiter
from app.middleware import get_principal, get_session
from app.models import Department
from app.pricing import estimate_cost_usd
from app.rbac import Permission, assert_department_access, require_permission


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


HERMES_SYSTEM_PROMPT = """\
You are Hermes, an agent embedded in a department of a company. Operate
against the user's connected tools (Composio, Browser Use) via MCP.

Slack:
- ALWAYS use the `slackbot` toolkit when posting to Slack, never `slack`.
  `slack` posts as the human; `slackbot` posts as the workspace bot. Even
  if both seem available, prefer slackbot. If only `slack` is available,
  tell the user to install the bot via the Connect page rather than
  posting as them.
- Bots can only post in channels they've been invited to. If a post
  fails with `not_in_channel`:
    1. First call the slackbot toolkit's auth.test (or users.info on the
       bot's own user_id from auth.test) to find the bot's actual
       username in this workspace. DO NOT GUESS the name — never tell
       the user to "/invite @slackbot" or "/invite @aki"; the real name
       depends on what the Composio Slack app is registered as.
    2. Tell the user the exact `/invite @<real-bot-name>` command to
       run, using the username you just looked up.
    3. After they invite, retry the post.

Gmail and other Composio tools: act on behalf of the user as expected.

Destructive actions (send email, post message, write to a database,
file/event creation): briefly confirm intent before executing if the
user's request is ambiguous. For clearly-requested actions, just do them.

Cite sources for any factual claims pulled from a tool.
"""


async def _resolve_department_id(
    request: Request, principal: Principal, db: AsyncSession
) -> UUID:
    """Resolve which department's Hermes container should handle this request.

    Order:
      1. `X-Hermes-Department` header (slug) — explicit caller choice.
      2. Principal's first membership — implicit "primary" department.
      3. Org's "default" department — backfilled by migration 0003 for every
         org. Catches users with zero memberships (e.g. freshly provisioned).
    """
    slug = request.headers.get("X-Hermes-Department")
    if slug:
        row = (
            await db.execute(
                select(Department.id).where(
                    Department.organization_id == principal.organization_id,
                    Department.slug == slug,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, f"department slug not found: {slug}")
        return row

    if principal.department_ids:
        return principal.department_ids[0]

    fallback = (
        await db.execute(
            select(Department.id).where(
                Department.organization_id == principal.organization_id,
                Department.slug == "default",
            )
        )
    ).scalar_one_or_none()
    if fallback is None:
        raise HTTPException(404, "no department for this user (and no default)")
    return fallback


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
    org_id, actor: str, dept_id, container_id: str,
    tool_events: list[dict], final_usage: dict | None,
    duration_ms: int, user_text: str, assistant_text: str,
) -> None:
    """Open a fresh session and write tool_call + chat.complete rows, plus
    a `brain_source(kind=chat_turn)` so future retrieval can cite this
    conversation.

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

        # Persist the full turn into Brain so future retrieval can cite it.
        if assistant_text.strip() or user_text.strip():
            try:
                from app.brain import persist_turn
                await persist_turn(
                    db, org_id, dept_id, actor,
                    kind="chat_turn",
                    user_text=user_text,
                    assistant_text=assistant_text,
                    origin="hermes",
                )
            except Exception:
                log.exception("brain ingest of chat turn failed")

        await db.commit()


@router.post("/chat/completions")
@limiter.limit("120/minute")
@org_limiter.limit("60/minute")
async def chat_completions(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.CHAT_CREATE)),
    db: AsyncSession = Depends(get_session),
):
    body = await request.body()
    # Inject Hermes' system prompt at the front of the messages list so the
    # agent has standing guidance (bot identity for Slack, ask before
    # destructive actions, etc.). We rewrite the request body in place.
    user_text = ""
    try:
        import json as _json
        body_dict = _json.loads(body) if body else {}
        msgs = body_dict.get("messages") or []
        # The last user message is the one being asked right now — use that
        # as the "instruction" when we index the chat turn into Brain.
        for m in reversed(msgs):
            if (m or {}).get("role") == "user":
                user_text = str(m.get("content") or "")
                break
        has_system = any((m or {}).get("role") == "system" for m in msgs)
        if not has_system:
            body_dict["messages"] = [{"role": "system", "content": HERMES_SYSTEM_PROMPT}, *msgs]
            body = _json.dumps(body_dict).encode("utf-8")
    except Exception:
        log.exception("system-prompt injection failed; passing body through")

    dept_id = await _resolve_department_id(request, principal, db)

    # RBAC: principal must have access to the resolved department.
    await assert_department_access(principal, dept_id, min_permission=Permission.CHAT_CREATE)

    # Enforce spend cap before expensive LLM call
    await enforce_spend_cap(db, principal.organization_id, estimated_cost=0.05)

    # Hydrate messages with Brain context before sending to Hermes
    try:
        body_dict = json.loads(body) if body else {}
        msgs = body_dict.get("messages") or []
        hydrated = await hydrate_messages(
            db, principal.organization_id, dept_id, principal.user_id, msgs, k=5
        )
        body_dict["messages"] = hydrated
        body = json.dumps(body_dict).encode("utf-8")
    except Exception:
        log.exception("brain hydration failed; continuing with original messages")

    proc: HermesProcess = await ensure_running(db, principal.organization_id, dept_id)

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="chat.start",
        target=proc.container_id,
        payload={"bytes": len(body), "department_id": str(dept_id)},
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
        assistant_parts: list[str] = []
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
                                continue
                            if isinstance(obj, dict):
                                # Accumulate assistant text from OpenAI delta
                                # chunks so we can index the turn into Brain.
                                for choice in obj.get("choices") or []:
                                    piece = ((choice or {}).get("delta") or {}).get("content")
                                    if isinstance(piece, str):
                                        assistant_parts.append(piece)
                                if "usage" in obj and obj["usage"]:
                                    final_usage = obj["usage"]
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await _flush_audit(
                    org_id, actor, dept_id, container_id,
                    tool_events, final_usage, duration_ms,
                    user_text, "".join(assistant_parts).strip(),
                )
            except Exception:
                log.exception("audit flush failed")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "X-Hermes-Org-Id": str(principal.organization_id),
            "X-Hermes-Container-Id": proc.container_id[:12],
            "Cache-Control": "no-cache",
        },
    )
