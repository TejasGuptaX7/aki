"""MCP server exposing native-OAuth providers' tools.

Mirrors /agent_internal/mcp (request_approval) in transport and auth:
  - Streamable HTTP MCP server (JSON-RPC 2.0 over POST)
  - Bearer service token whose sha256 matches `agents.service_token_hash`
  - X-Aki-Org-Id / X-Aki-Agent-Id headers identify the calling profile

Tool execution rule: given a tool name like `gmail_send_message`, we look
up which native handler owns it, then find the right active Connection
in (org_id, agent_id) scope. If no Connection exists, return a structured
error the agent can surface to the user ("you haven't connected Gmail
yet — go to /connect").

Connection selection precedence: agent-scoped row wins over org-wide,
matching docs/architecture.md §6. So an agent with its own Gmail account
will use that, falling back to org's shared account, otherwise erroring.

The handler's `refresh_token()` runs before every tool call. Cheap (single
DB write + maybe a token endpoint round-trip) and avoids stale-token 401s
mid-task.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Request
from sqlalchemy import and_, or_, select

from app.audit import append_audit
from app.db import session_for_org
from app.models import Connection
from app.oauth import NATIVE_HANDLERS, NativeOAuthError, get_handler
from app.routes.agent_internal import _verify_agent  # reuse the auth helper


log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent_internal", tags=["agent_internal"])


# ── MCP JSON-RPC primitives (copied from agent_internal.py for locality) ────


def _rpc_ok(rid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_err(rid: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def _tool_result(content_obj: Any, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(content_obj, default=str)}],
        "isError": is_error,
    }


# ── Tool ↔ provider routing ────────────────────────────────────────────────


def _build_tool_index() -> dict[str, tuple[str, Any]]:
    """Map tool name → (provider_slug, NativeToolSpec). Rebuilt once at
    module import; handler registration happens at import time so this is
    stable for the life of the process."""
    index: dict[str, tuple[str, Any]] = {}
    for slug, handler in NATIVE_HANDLERS.items():
        for spec in handler.tools():
            if spec.name in index:
                raise RuntimeError(
                    f"native tool name collision: {spec.name} declared by "
                    f"{index[spec.name][0]} and {slug}"
                )
            index[spec.name] = (slug, spec)
    return index


_TOOL_INDEX = _build_tool_index()


def _tool_catalogue() -> list[dict]:
    """`tools/list` reply — the MCP-shape list of every native tool."""
    out: list[dict] = []
    for name, (slug, spec) in _TOOL_INDEX.items():
        out.append(
            {
                "name": name,
                "description": spec.description,
                "inputSchema": spec.input_schema,
            }
        )
    return out


async def _find_connection(
    org_id: UUID, agent_id: UUID, provider_slug: str
) -> Connection | None:
    """Return the most-specific active Connection for this (org, agent,
    provider). Agent-scoped beats org-wide; ties broken by created_at desc
    (most recent install wins, in case the user reconnected after revoking).
    """
    handler = get_handler(provider_slug)
    async with session_for_org(org_id) as db:
        rows = (
            await db.execute(
                select(Connection)
                .where(
                    and_(
                        Connection.organization_id == org_id,
                        Connection.provider == handler.display_provider,
                        Connection.status == "active",
                        or_(
                            Connection.agent_id.is_(None),
                            Connection.agent_id == agent_id,
                        ),
                    )
                )
                .order_by(
                    # `agent_id IS NULL` sorts last when DESC, so non-null
                    # (agent-scoped) rows win first; created_at breaks ties.
                    Connection.agent_id.desc().nulls_last(),
                    Connection.created_at.desc(),
                )
                .limit(1)
            )
        ).scalars().all()
        return rows[0] if rows else None


async def _execute_tool(
    org_id: UUID,
    agent_id: UUID,
    name: str,
    args: dict,
) -> dict:
    """Resolve the tool, find the connection, refresh if needed, call it.
    Returns an MCP-shape `_tool_result` dict ready for inclusion in a
    JSON-RPC response."""
    if name not in _TOOL_INDEX:
        return _tool_result(
            {"code": "unknown_tool", "detail": f"no such native tool: {name}"},
            is_error=True,
        )
    provider_slug, spec = _TOOL_INDEX[name]
    handler = get_handler(provider_slug)

    conn = await _find_connection(org_id, agent_id, provider_slug)
    if conn is None:
        return _tool_result(
            {
                "code": "not_connected",
                "provider": provider_slug,
                "detail": (
                    f"no active {provider_slug} connection for this org/agent. "
                    f"User needs to visit /connect and authorize {provider_slug}."
                ),
            },
            is_error=True,
        )

    try:
        async with session_for_org(org_id) as db:
            # refresh_token() may rewrite conn.config — re-attach + commit.
            conn = await db.merge(conn)
            await handler.refresh_token(conn, db)
            await db.commit()

            result = await spec.caller(args or {}, conn, db)
            await append_audit(
                db,
                org_id,
                actor=f"agent:{agent_id}",
                action="tool.execute",
                target=name,
                payload={
                    "provider": provider_slug,
                    "connection_id": str(conn.id),
                },
                agent_id=agent_id,
            )
            await db.commit()
    except NativeOAuthError as e:
        log.warning(
            "native tool %s failed for org=%s: status=%s body=%s",
            name, org_id, e.status, e.body,
        )
        return _tool_result(
            {
                "code": "provider_error",
                "provider": provider_slug,
                "status": e.status,
                "detail": str(e),
            },
            is_error=True,
        )
    except Exception as e:
        log.exception("native tool %s crashed for org=%s", name, org_id)
        return _tool_result(
            {"code": "internal_error", "detail": str(e)[:200]},
            is_error=True,
        )

    return _tool_result(result)


# ── MCP endpoint ───────────────────────────────────────────────────────────


@router.post("/native_mcp")
async def mcp(
    request: Request,
    authorization: str | None = Header(None),
    x_aki_org_id: str | None = Header(None, alias="X-Aki-Org-Id"),
    x_aki_agent_id: str | None = Header(None, alias="X-Aki-Agent-Id"),
) -> dict:
    org_id, agent_id = await _verify_agent(
        authorization, x_aki_org_id, x_aki_agent_id
    )

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
            "serverInfo": {"name": "aki-native", "version": "0.1.0"},
        })
    if method == "notifications/initialized":
        return {}
    if method == "tools/list":
        return _rpc_ok(rid, {"tools": _tool_catalogue()})
    if method == "tools/call":
        name = (params or {}).get("name") or ""
        args = (params or {}).get("arguments") or {}
        if not isinstance(args, dict):
            return _rpc_ok(rid, _tool_result(
                {"code": "bad_args", "detail": "arguments must be an object"},
                is_error=True,
            ))
        out = await _execute_tool(org_id, agent_id, name, args)
        return _rpc_ok(rid, out)
    return _rpc_err(rid, -32601, f"method not found: {method}")
