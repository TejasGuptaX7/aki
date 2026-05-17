"""Internal MCP server for agent → control-plane calls.

A minimal Streamable HTTP MCP server (JSON-RPC 2.0 over POST) that runs
inside the control-plane API and exposes tools the agent can call back
into the control plane to use. v1 exposes ONE tool: `request_approval`.

Wire contract (mirrors services/browser-harness/PROTOCOL.md so future
internal tools follow the same shape):

  Endpoint:   POST /agent_internal/mcp        (this file)
  Headers:    Authorization: Bearer <per-agent service token>
              X-Aki-Org-Id:   <org uuid>
              X-Aki-Agent-Id: <agent uuid>
              Content-Type:   application/json
  Body:       JSON-RPC 2.0 envelope (initialize / tools/list / tools/call)

Auth: token hash matches `agents.service_token_hash` AND the agent row's
(id, organization_id) matches the headers. Mismatched headers → 401.

Tools (v1):
  request_approval(kind: str, tool: str, args: dict, summary: str)
    → creates a pending approval row in this agent's org,
      long-polls /approvals/{id}/wait until status changes or expires,
      returns {"approved": bool, "status": "approved|denied|expired",
              "approval_id": str, "responded_by": str | null}
    The agent calls this BEFORE running any tier-2 action; conditional
    on the boolean it either proceeds or apologizes to the user.

Why MCP and not REST: Hermes natively speaks MCP for tool discovery;
adding this as one more MCP server in the agent's config means the
agent's planner sees `request_approval` alongside `gmail_send`,
`slack_post`, etc., as a normal tool. A REST endpoint would require the
agent to know about the URL + format via system prompt only, which is
brittle.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from app import agent_runs as runs_mod
from app import agent_tokens
from app.audit import append_audit
from app.db import session_for_org
from app.models import Agent, Approval, Notification


log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent_internal", tags=["agent_internal"])


# Long-poll cap: 50s leaves headroom under the typical 60s LB idle timeout.
WAIT_MAX_S = 50.0
WAIT_POLL_INTERVAL_S = 0.5
DEFAULT_APPROVAL_TTL = timedelta(minutes=10)


# ── MCP JSON-RPC primitives ────────────────────────────────────────────────


def _rpc_ok(rid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_err(rid: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def _tool_result(content_obj: dict, *, is_error: bool = False) -> dict:
    """Wrap a JSON-serializable object in the MCP content[] shape."""
    import json
    return {
        "content": [{"type": "text", "text": json.dumps(content_obj)}],
        "isError": is_error,
    }


# ── Auth ───────────────────────────────────────────────────────────────────


async def _verify_agent(
    bearer: str | None,
    org_id_hdr: str | None,
    agent_id_hdr: str | None,
) -> tuple[UUID, UUID]:
    """Authenticate a request from an agent's Hermes profile. Returns
    (org_id, agent_id) on success; raises 401 on any mismatch."""
    if not bearer or not bearer.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = bearer.removeprefix("Bearer ").strip()

    try:
        org_id = UUID(org_id_hdr) if org_id_hdr else None
        agent_id = UUID(agent_id_hdr) if agent_id_hdr else None
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "header UUIDs invalid")
    if org_id is None or agent_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "X-Aki-Org-Id and X-Aki-Agent-Id required",
        )

    # Look up the agent without RLS — the bearer token IS the auth, and we
    # don't have an org context yet (we're about to establish one).
    from sqlalchemy import text
    from app.db import SessionLocal

    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        agent = await db.scalar(
            select(Agent).where(Agent.id == agent_id)
        )
    if agent is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "agent not found")
    if agent.organization_id != org_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "agent/org mismatch")
    if not agent.service_token_hash:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "agent has no service token; reprovision the profile",
        )
    if not agent_tokens.verify(token, agent.service_token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad service token")
    return org_id, agent_id


# ── Tool: request_approval ─────────────────────────────────────────────────


async def _create_and_wait(
    org_id: UUID,
    agent_id: UUID,
    kind: str,
    tool: str,
    args: dict,
    summary: str,
) -> dict:
    """Create an approval row, long-poll until decided or expired, return
    the wire shape the agent gets back."""
    now = datetime.now(timezone.utc)
    approval_id = uuid4()

    async with session_for_org(org_id) as db:
        row = Approval(
            id=approval_id,
            organization_id=org_id,
            agent_id=agent_id,
            action=kind,
            tool=tool,
            args=args or {},
            reason=summary or "",
            status="pending",
            expires_at=now + DEFAULT_APPROVAL_TTL,
        )
        db.add(row)
        await append_audit(
            db,
            org_id,
            actor=f"agent:{agent_id}",
            action="approval.request",
            target=str(approval_id),
            payload={"kind": kind, "tool": tool},
            agent_id=agent_id,
        )
        await db.commit()

    # Long-poll: each loop opens its own session so we don't hold a
    # connection idle for the full wait (NeonDB pooler cares).
    deadline = asyncio.get_running_loop().time() + WAIT_MAX_S
    final_status = "expired"
    responded_by: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(WAIT_POLL_INTERVAL_S)
        async with session_for_org(org_id) as db:
            row = await db.scalar(
                select(Approval).where(Approval.id == approval_id)
            )
            if row is None:
                final_status = "missing"
                break
            now = datetime.now(timezone.utc)
            if row.status != "pending":
                final_status = row.status
                responded_by = row.responded_by
                break
            if row.expires_at <= now:
                final_status = "expired"
                break
    else:
        # Loop exited via deadline without a status change. The DB row stays
        # `pending` until either the user responds late or the table's expiry
        # is reached; the agent gets "pending_timeout" so it can decide to
        # retry (call wait again) or abandon.
        final_status = "pending_timeout"

    return {
        "approved": final_status == "approved",
        "status": final_status,
        "approval_id": str(approval_id),
        "responded_by": responded_by,
    }


# ── MCP endpoint ───────────────────────────────────────────────────────────


_TOOL_CATALOGUE = [
    {
        "name": "update_plan",
        "description": (
            "Declare or revise your plan for the current run. Pass the FULL "
            "ordered list of steps you intend to take. You may call this "
            "more than once; the latest call wins. Each step is an object "
            "{text: str, status?: 'pending'|'in_progress'|'done'|'skipped'}. "
            "Use this at the start of any long task so the user can see "
            "what you're going to do, and again whenever the plan changes. "
            "Resolves the current run by (org, agent) — no run_id needed. "
            "Returns {run_id, step_count} or {error}."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["steps"],
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": [
                                    "pending", "in_progress", "done", "skipped",
                                ],
                            },
                        },
                    },
                },
            },
        },
    },
    {
        "name": "notify_user",
        "description": (
            "Emit an ambient notification the user will see in their inbox. "
            "Use this to surface a completed long task ('Done: weekly "
            "report ready'), a wall you hit ('Stuck: need the Acme contract "
            "PDF'), or a question that doesn't block a tool call. For "
            "approval-required actions, use `request_approval` instead — "
            "this tool does not pause execution. Returns "
            "{notification_id} or {error}."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short headline. Max 200 chars.",
                },
                "body": {
                    "type": "string",
                    "description": "Optional longer body. Markdown OK.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["question", "done", "error"],
                    "description": (
                        "Default 'done'. 'question' surfaces with a "
                        "reply CTA; 'error' renders with a warning icon."
                    ),
                },
            },
        },
    },
    {
        "name": "request_approval",
        "description": (
            "Ask the human to approve a tier-2 action (external email, "
            "public post, account signup, anything irreversible) before "
            "running it. Returns {approved: bool, status, approval_id, "
            "responded_by}. Long-polls up to 50s; if status is "
            "'pending_timeout' the human hasn't responded yet — you may "
            "call this again with the same approval_id (TODO) or fall back "
            "to telling the user the request is waiting in their inbox."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["kind", "tool", "summary"],
            "properties": {
                "kind": {
                    "type": "string",
                    "description": (
                        "Short action category, e.g. 'email.send', "
                        "'account.create', 'post.public'."
                    ),
                },
                "tool": {
                    "type": "string",
                    "description": (
                        "The actual MCP tool name you're about to call "
                        "(e.g. 'gmail_send_message'). For audit + future "
                        "policy filtering."
                    ),
                },
                "args": {
                    "type": "object",
                    "description": (
                        "The args you'd pass to the tool. Shown verbatim "
                        "to the user so they know what they're approving."
                    ),
                    "default": {},
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "One-line human-readable description. e.g. 'Send "
                        "reply to john@acme.com about Q3 contract'."
                    ),
                },
            },
        },
    },
]


async def _handle_update_plan(
    org_id: UUID, agent_id: UUID, args: dict
) -> dict:
    """Resolve the agent's current run and replace its plan. The agent
    never sees a run_id — there is at most one active run per (org, agent)
    that the agent should care about."""
    steps = args.get("steps")
    if not isinstance(steps, list):
        return {"code": "bad_args", "detail": "steps must be an array"}

    async with session_for_org(org_id) as db:
        run = await runs_mod.get_current_run(db, org_id, agent_id)
        if run is None:
            return {
                "code": "no_active_run",
                "detail": (
                    "no currently running agent_run for this agent; "
                    "the chat completion must be invoked via POST "
                    "/agents/{id}/runs or a schedule to open one"
                ),
            }
        updated = await runs_mod.update_plan(db, org_id, run.id, steps)
        if updated is None:
            return {"code": "not_found", "detail": "run vanished mid-update"}
        await append_audit(
            db, org_id,
            actor=f"agent:{agent_id}",
            action="run.update_plan",
            target=str(run.id),
            payload={"step_count": len(steps)},
            agent_id=agent_id,
        )
        await db.commit()
        return {"run_id": str(run.id), "step_count": len(steps)}


async def _handle_notify_user(
    org_id: UUID, agent_id: UUID, args: dict
) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return {"code": "bad_args", "detail": "title is required"}
    if len(title) > 200:
        title = title[:200]
    body = (args.get("body") or "")
    if len(body) > 8_000:
        body = body[:8_000]
    kind = (args.get("kind") or "done").strip()
    if kind not in ("question", "done", "error"):
        kind = "done"

    notif_id = uuid4()
    async with session_for_org(org_id) as db:
        n = Notification(
            id=notif_id,
            organization_id=org_id,
            agent_id=agent_id,
            kind=kind,
            title=title,
            body=body,
            payload={},
        )
        db.add(n)
        await append_audit(
            db, org_id,
            actor=f"agent:{agent_id}",
            action="notification.create",
            target=str(notif_id),
            payload={"kind": kind, "title_len": len(title)},
            agent_id=agent_id,
        )
        await db.commit()
    return {"notification_id": str(notif_id), "kind": kind}


async def _handle_tool_call(
    org_id: UUID,
    agent_id: UUID,
    rid: Any,
    params: dict,
) -> dict:
    name = (params or {}).get("name") or ""
    args = (params or {}).get("arguments") or {}

    if name == "update_plan":
        try:
            out = await _handle_update_plan(org_id, agent_id, args)
        except Exception as e:
            log.exception("update_plan failed org=%s agent=%s", org_id, agent_id)
            return _rpc_ok(rid, _tool_result(
                {"code": "internal_error", "detail": str(e)[:200]},
                is_error=True,
            ))
        return _rpc_ok(rid, _tool_result(
            out, is_error=bool(out.get("code")),
        ))

    if name == "notify_user":
        try:
            out = await _handle_notify_user(org_id, agent_id, args)
        except Exception as e:
            log.exception("notify_user failed org=%s agent=%s", org_id, agent_id)
            return _rpc_ok(rid, _tool_result(
                {"code": "internal_error", "detail": str(e)[:200]},
                is_error=True,
            ))
        return _rpc_ok(rid, _tool_result(
            out, is_error=bool(out.get("code")),
        ))

    if name != "request_approval":
        return _rpc_ok(rid, _tool_result(
            {"code": "unknown_tool", "detail": f"no such tool: {name}"},
            is_error=True,
        ))

    kind = (args.get("kind") or "").strip()
    tool = (args.get("tool") or "").strip()
    summary = (args.get("summary") or "").strip()
    tool_args = args.get("args") or {}
    if not kind or not tool:
        return _rpc_ok(rid, _tool_result(
            {"code": "bad_args", "detail": "kind and tool are required"},
            is_error=True,
        ))
    if not isinstance(tool_args, dict):
        return _rpc_ok(rid, _tool_result(
            {"code": "bad_args", "detail": "args must be an object"},
            is_error=True,
        ))

    try:
        out = await _create_and_wait(
            org_id, agent_id, kind, tool, tool_args, summary
        )
    except Exception as e:
        log.exception("request_approval failed org=%s agent=%s", org_id, agent_id)
        return _rpc_ok(rid, _tool_result(
            {"code": "internal_error", "detail": str(e)[:200]},
            is_error=True,
        ))
    return _rpc_ok(rid, _tool_result(out))


@router.post("/mcp")
async def mcp(
    request: Request,
    authorization: str | None = Header(None),
    x_aki_org_id: str | None = Header(None, alias="X-Aki-Org-Id"),
    x_aki_agent_id: str | None = Header(None, alias="X-Aki-Agent-Id"),
) -> dict:
    org_id, agent_id = await _verify_agent(
        authorization, x_aki_org_id, x_aki_agent_id
    )

    # Parse the JSON-RPC envelope. Spec allows batched requests; v1 only
    # supports single-request bodies (Hermes sends single requests).
    try:
        body = await request.json()
    except Exception:
        return {
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32700, "message": "parse error"},
        }

    if not isinstance(body, dict):
        return {
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32600, "message": "batched requests not supported"},
        }

    rid = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return _rpc_ok(rid, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "aki-internal", "version": "0.1.0"},
        })
    if method == "notifications/initialized":
        # No response per spec.
        return {}  # FastAPI will serialize as {}; Hermes ignores
    if method == "tools/list":
        return _rpc_ok(rid, {"tools": _TOOL_CATALOGUE})
    if method == "tools/call":
        return await _handle_tool_call(org_id, agent_id, rid, params)
    return _rpc_err(rid, -32601, f"method not found: {method}")
