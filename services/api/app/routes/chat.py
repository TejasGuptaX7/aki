"""OpenAI-compatible chat completions proxy.

POST /v1/chat/completions →
  1. RBAC stub (returns True for v1; layered later when memberships land)
  2. ensure_running(org_id) — cold-starts the per-org Hermes container if needed
  3. forward request body to Hermes' OpenAI-compat API with the per-org bearer
  4. stream the response straight back to the client

Audit log writes from the agent's tool calls flow in via a separate consumer
(Phase 2c — Hermes SSE event stream → audit_log table). We do NOT intercept
each tool call here; that would put Aki on the latency hot path of every
MCP call for no benefit.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import ensure_running
from app.audit import append_audit
from app.auth import Principal
from app.middleware import get_principal, get_session


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


async def _rbac_check(principal: Principal, action: str) -> None:
    """v1 stub. Returns silently if allowed, raises HTTPException(403) if not.
    Replace with real check when memberships table lands."""
    return None


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    await _rbac_check(principal, "chat.send")

    body = await request.body()
    proc = await ensure_running(db, principal.organization_id)

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

    async def stream():
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as c:
            async with c.stream(
                "POST",
                f"{proc.base_url}/v1/chat/completions",
                content=body,
                headers=headers,
            ) as upstream:
                async for chunk in upstream.aiter_raw():
                    yield chunk

    return StreamingResponse(
        stream(),
        media_type="application/json",
        headers={"X-Aki-Org-Id": str(principal.organization_id)},
    )
