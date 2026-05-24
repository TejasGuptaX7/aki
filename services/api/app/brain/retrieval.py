"""Hybrid retrieval: pgvector cosine + tsvector BM25, fused via RRF.

ACL principals are filtered *after* RRF rather than inside SQL so the SQL
stays small and easy to debug. Each `brain_sources` row carries an
`acl_principals` JSON array snapshotted at ingest time; retrieval principals
(typically `[org_id, dept_id, user_id]`) must intersect that list non-emptily
to be eligible.

Live ACL re-checks against the source provider (Slack/Notion/Drive) are
deferred to a later phase — see docs/architecture.md §8.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.acl import is_allowed
from app.brain.embeddings import embed
from app.brain.reranker import rerank

CANDIDATE_N = 50  # vector + BM25 candidates merged before RRF
RRF_CONSTANT = 60  # standard RRF dampener


@dataclass(frozen=True)
class BrainHit:
    source_id: UUID
    chunk_id: UUID
    title: str | None
    content: str
    score: float
    provenance: dict


async def retrieve(
    db: AsyncSession,
    org_id: UUID,
    *,
    query: str,
    principals: Iterable[str],
    k: int = 8,
    scope_filter: str | None = None,  # 'org' | 'department' | 'user' | None
) -> list[BrainHit]:
    """Retrieve top-k brain chunks for `query` under `principals`."""
    if not query.strip():
        return []

    query_vec = (await embed([query]))[0]
    principal_set = {str(p) for p in principals}

    # Vector top-N: cosine distance ASC (smaller = closer).
    vec_rows = (
        (
            await db.execute(
                text("""
                select c.id as chunk_id, c.source_id, c.content,
                       s.title, s.acl_principals, s.kind, s.origin,
                       s.uri, s.scope, s.scope_id,
                       (c.embedding <=> (:qv)::vector) as distance
                from brain_chunks c
                join brain_sources s on s.id = c.source_id
                where c.organization_id = :org
                  and (:scope_filter is null or s.scope = :scope_filter)
                order by c.embedding <=> (:qv)::vector
                limit :n
            """),
                {
                    "qv": query_vec,
                    "org": str(org_id),
                    "n": CANDIDATE_N,
                    "scope_filter": scope_filter,
                },
            )
        )
        .mappings()
        .all()
    )

    # BM25 top-N via tsvector + ts_rank_cd.
    bm25_rows = (
        (
            await db.execute(
                text("""
                select c.id as chunk_id, c.source_id, c.content,
                       s.title, s.acl_principals, s.kind, s.origin,
                       s.uri, s.scope, s.scope_id,
                       ts_rank_cd(c.ts_vector, plainto_tsquery('english', :q)) as rank
                from brain_chunks c
                join brain_sources s on s.id = c.source_id
                where c.organization_id = :org
                  and (:scope_filter is null or s.scope = :scope_filter)
                  and c.ts_vector @@ plainto_tsquery('english', :q)
                order by rank desc
                limit :n
            """),
                {
                    "q": query,
                    "org": str(org_id),
                    "n": CANDIDATE_N,
                    "scope_filter": scope_filter,
                },
            )
        )
        .mappings()
        .all()
    )

    # Reciprocal rank fusion: score = sum over lists of 1 / (k + rank).
    fused: dict[UUID, dict[str, Any]] = {}
    for rank, vrow in enumerate(vec_rows):
        cid = vrow["chunk_id"]
        fused.setdefault(cid, dict(vrow))
        fused[cid]["_score"] = fused[cid].get("_score", 0.0) + 1.0 / (RRF_CONSTANT + rank + 1)
    for rank, brow in enumerate(bm25_rows):
        cid = brow["chunk_id"]
        fused.setdefault(cid, dict(brow))
        fused[cid]["_score"] = fused[cid].get("_score", 0.0) + 1.0 / (RRF_CONSTANT + rank + 1)

    # ACL filter — snapshot intersection first, then optional live recheck.
    # We do the cheap snapshot check inline and only live-check survivors.
    snapshot_eligible: list[dict[str, Any]] = []
    for entry in fused.values():
        acl = entry.get("acl_principals") or []
        if isinstance(acl, list) and principal_set.intersection(map(str, acl)):
            snapshot_eligible.append(entry)

    snapshot_eligible.sort(key=lambda r: r["_score"], reverse=True)

    # Live recheck — applied only to the top candidates so we don't pay
    # provider RTTs on rows the user will never see.
    eligible: list[dict[str, Any]] = []
    for entry in snapshot_eligible[: k * 2]:  # 2× headroom for ACL drops
        allowed = await is_allowed(
            entry["source_id"],
            entry.get("origin") or "",
            entry.get("uri"),
            entry.get("acl_principals") or [],
            principal_set,
            org_id=org_id,
        )
        if allowed:
            eligible.append(entry)
        if len(eligible) >= k:
            break

    # Cross-encoder rerank the ACL-filtered candidates for better ordering.
    passages = [entry["content"] for entry in eligible[:k]]
    reranked = rerank(query, passages, top_k=k)

    hits: list[BrainHit] = []
    for original_idx, rerank_score in reranked:
        row = eligible[original_idx]
        hits.append(
            BrainHit(
                source_id=row["source_id"],
                chunk_id=row["chunk_id"],
                title=row.get("title"),
                content=row["content"],
                score=float(rerank_score),
                provenance={
                    "kind": row.get("kind"),
                    "origin": row.get("origin"),
                    "uri": row.get("uri"),
                    "scope": row.get("scope"),
                    "scope_id": str(row["scope_id"]) if row.get("scope_id") else None,
                },
            )
        )
    return hits
