"""Brain — ingest, retrieve, list-sources.

Every ingest/retrieve writes one audit row through the existing hash-chain
so we have a tamper-evident trail of *what context the agent saw* for a
given turn.

ACL semantics:
- On ingest, callers may pass `acl_principals`. If omitted, we default to
  `[org_id, dept_id?, user_id]` for the writing principal.
- On retrieve, the requester's principals are `[org_id, *department_ids,
  user_id]`. Intersection happens after RRF in `brain.retrieval`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.auth import Principal
from app.brain.chunker import chunk_text
from app.brain.embeddings import embed
from app.brain.retrieval import retrieve as retrieve_hits
from app.config import get_settings
from app.db import session_for_org
from app.middleware import get_principal, get_session
from app.models import BrainChunk, BrainSource


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/brain", tags=["brain"])


class IngestBody(BaseModel):
    scope: Literal["org", "department", "user"]
    scope_id: UUID | None = None
    kind: str = Field(..., min_length=1, max_length=64)
    origin: str = Field(..., min_length=1, max_length=32)
    uri: str | None = Field(default=None, max_length=1024)
    title: str | None = Field(default=None, max_length=512)
    content: str = Field(..., min_length=1)
    acl_principals: list[str] | None = None


class IngestResponse(BaseModel):
    source_id: UUID
    chunks: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    body: IngestBody,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> IngestResponse:
    settings = get_settings()

    # Idempotency: if (origin, uri) already exists for this org, return its id.
    if body.uri:
        existing = (
            await db.execute(
                select(BrainSource.id).where(
                    BrainSource.organization_id == principal.organization_id,
                    BrainSource.origin == body.origin,
                    BrainSource.uri == body.uri,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            count = (
                await db.execute(
                    select(BrainChunk.id).where(BrainChunk.source_id == existing)
                )
            ).all()
            return IngestResponse(source_id=existing, chunks=len(count))

    # Default ACL: writer's principals if not specified.
    acl = body.acl_principals or _default_acl(principal)

    source = BrainSource(
        id=uuid4(),
        organization_id=principal.organization_id,
        scope=body.scope,
        scope_id=body.scope_id,
        kind=body.kind,
        origin=body.origin,
        uri=body.uri,
        title=body.title,
        acl_principals=acl,
    )
    db.add(source)
    await db.flush()

    chunks = chunk_text(
        body.content,
        target_tokens=settings.brain_chunk_tokens,
        overlap_chars=settings.brain_chunk_overlap,
    )
    if chunks:
        embeddings = await embed([c.content for c in chunks])
        for chunk, vec in zip(chunks, embeddings):
            db.add(
                BrainChunk(
                    id=uuid4(),
                    source_id=source.id,
                    organization_id=principal.organization_id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding=vec,
                )
            )

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="brain.ingest",
        target=str(source.id),
        payload={
            "kind": body.kind,
            "origin": body.origin,
            "scope": body.scope,
            "uri": body.uri,
            "chunks": len(chunks),
            "title": body.title,
        },
    )
    await db.commit()

    return IngestResponse(source_id=source.id, chunks=len(chunks))


class RetrieveBody(BaseModel):
    query: str = Field(..., min_length=1)
    k: int = Field(default=8, ge=1, le=50)
    scope_filter: Literal["org", "department", "user"] | None = None


class RetrieveHitOut(BaseModel):
    source_id: UUID
    chunk_id: UUID
    title: str | None
    content: str
    score: float
    provenance: dict[str, Any]


class RetrieveResponse(BaseModel):
    hits: list[RetrieveHitOut]


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveBody,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> RetrieveResponse:
    principals = _default_acl(principal)
    hits = await retrieve_hits(
        db,
        principal.organization_id,
        query=body.query,
        principals=principals,
        k=body.k,
        scope_filter=body.scope_filter,
    )

    await append_audit(
        db,
        principal.organization_id,
        actor=principal.user_id,
        action="brain.retrieve",
        target=None,
        payload={
            "query": body.query[:512],
            "k": body.k,
            "scope_filter": body.scope_filter,
            "hits": len(hits),
            "hit_source_ids": [str(h.source_id) for h in hits],
        },
    )
    await db.commit()

    return RetrieveResponse(
        hits=[
            RetrieveHitOut(
                source_id=h.source_id,
                chunk_id=h.chunk_id,
                title=h.title,
                content=h.content,
                score=h.score,
                provenance=h.provenance,
            )
            for h in hits
        ]
    )


class SourceOut(BaseModel):
    id: UUID
    scope: str
    scope_id: UUID | None
    kind: str
    origin: str
    uri: str | None
    title: str | None
    created_at: datetime


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    scope: Literal["org", "department", "user"] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> list[SourceOut]:
    q = select(BrainSource).where(
        BrainSource.organization_id == principal.organization_id
    )
    if scope:
        q = q.where(BrainSource.scope == scope)
    q = q.order_by(BrainSource.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [
        SourceOut(
            id=r.id,
            scope=r.scope,
            scope_id=r.scope_id,
            kind=r.kind,
            origin=r.origin,
            uri=r.uri,
            title=r.title,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _default_acl(principal: Principal) -> list[str]:
    """Default ACL principals: [org_id, *department_ids, user_id]."""
    out = [str(principal.organization_id), *map(str, principal.department_ids)]
    out.append(principal.user_id)
    return out


@router.get("/export")
async def export_jsonl(
    kinds: str = Query(
        "job_summary,aki_journal",
        description="Comma-separated brain_sources.kind values to include.",
    ),
    principal: Principal = Depends(get_principal),
) -> StreamingResponse:
    """Stream a JSONL training dataset built from Brain.

    Each line is `{"instruction", "context", "response", "signals"}` shaped
    for SFT/LoRA training of Qwen (or any chat-model). Sources of kind
    `job_summary` produce the highest-signal rows (brief → assistant
    final summary); `aki_journal` provides per-user context lines.

    Audited as `brain.export` after the stream is consumed; we log the
    requested kinds + a checksum of the principal who exported.
    """
    requested = {k.strip() for k in kinds.split(",") if k.strip()}
    org_id = principal.organization_id

    async def gen():
        rows_yielded = 0
        async with session_for_org(org_id) as db:
            # Stream job-summary rows as instruction-response pairs.
            if "job_summary" in requested:
                async for row in _stream_job_summaries(db, org_id):
                    yield (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
                    rows_yielded += 1

            # aki_journal sources go in as plain context lines (no explicit
            # instruction). The training pipeline can wrap these later.
            if "aki_journal" in requested:
                async for row in _stream_journal(db, org_id):
                    yield (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
                    rows_yielded += 1

        # Best-effort audit after the stream closes. We open a fresh
        # session because the streaming session is closed by now.
        try:
            async with session_for_org(org_id) as db:
                await append_audit(
                    db, org_id, actor=principal.user_id,
                    action="brain.export", target=None,
                    payload={"kinds": sorted(requested), "rows": rows_yielded},
                )
                await db.commit()
        except Exception:
            log.exception("brain.export audit write failed")

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": (
                f'attachment; filename="brain-{org_id}.jsonl"'
            ),
        },
    )


async def _stream_job_summaries(db, org_id: UUID):
    """Yield instruction/response rows derived from completed jobs.

    SQL stays small: join brain_sources(kind=job_summary) with jobs by
    uri='job://<id>' to recover the original brief.
    """
    result = await db.stream(
        text("""
            select s.id as source_id, s.title, s.uri, s.created_at,
                   j.brief, j.result_summary, j.cost_usd, j.department_id
            from brain_sources s
            join jobs j on j.brain_source_id = s.id
            where s.organization_id = :org and s.kind = 'job_summary'
              and j.result_summary is not null
              and length(j.result_summary) > 0
            order by s.created_at desc
        """),
        {"org": str(org_id)},
    )
    async for r in result.mappings():
        yield {
            "instruction": r["brief"],
            "context": "",  # Brain retrieval is the context source at run time
            "response": r["result_summary"],
            "signals": {
                "kind": "job_summary",
                "source_id": str(r["source_id"]),
                "department_id": str(r["department_id"]),
                "cost_usd": float(r["cost_usd"] or 0),
                "created_at": r["created_at"].isoformat(),
            },
        }


async def _stream_journal(db, org_id: UUID):
    """Yield rows from aki_journal sources — typed/dictated employee notes."""
    result = await db.stream(
        text("""
            select s.id as source_id, s.title, s.uri, s.created_at,
                   string_agg(c.content, '\n\n' order by c.chunk_index) as body
            from brain_sources s
            join brain_chunks c on c.source_id = s.id
            where s.organization_id = :org and s.kind = 'aki_journal'
            group by s.id, s.title, s.uri, s.created_at
            order by s.created_at desc
        """),
        {"org": str(org_id)},
    )
    async for r in result.mappings():
        yield {
            "instruction": "",
            "context": r["body"],
            "response": "",
            "signals": {
                "kind": "aki_journal",
                "source_id": str(r["source_id"]),
                "created_at": r["created_at"].isoformat(),
                "uri": r["uri"],
            },
        }
