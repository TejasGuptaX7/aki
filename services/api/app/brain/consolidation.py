"""Memory consolidation pipeline.

Nightly job that compresses episodic memories (chat turns, job summaries) into:
1. Semantic facts (structured key-value pairs with validity windows)
2. Procedural patterns (repeated successful tool sequences)
3. Episode summaries (compressed narratives of old conversations)

This prevents linear growth of the vector store and improves retrieval quality
by surfacing higher-level abstractions.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.chunker import chunk_text
from app.brain.embeddings import embed
from app.config import get_settings
from app.models import BrainChunk, BrainFact, BrainSource, Job

log = logging.getLogger(__name__)


async def run_consolidation(db: AsyncSession, org_id: UUID) -> dict:
    """Run the full consolidation pipeline for one organization.

    Returns a summary dict of what was created.
    """
    log.info("consolidation started for org=%s", org_id)
    results = {"facts": 0, "patterns": 0, "summaries": 0, "errors": []}

    try:
        facts = await _extract_facts(db, org_id)
        results["facts"] = len(facts)
    except Exception as e:
        log.exception("fact extraction failed for org=%s", org_id)
        results["errors"].append(f"facts: {e}")

    try:
        patterns = await _extract_patterns(db, org_id)
        results["patterns"] = len(patterns)
    except Exception as e:
        log.exception("pattern extraction failed for org=%s", org_id)
        results["errors"].append(f"patterns: {e}")

    try:
        summaries = await _summarize_old_episodes(db, org_id)
        results["summaries"] = summaries
    except Exception as e:
        log.exception("episode summarization failed for org=%s", org_id)
        results["errors"].append(f"summaries: {e}")

    log.info("consolidation complete for org=%s: %s", org_id, results)
    return results


async def _extract_facts(db: AsyncSession, org_id: UUID) -> list[BrainFact]:
    """Extract structured facts from recent job summaries and chat turns.

    For v1, we use a simple heuristic-based approach:
    - Look for key-value patterns in job summaries
    - Store as BrainFact with high confidence

    Phase 5: Replace with LLM-based extraction for richer semantic facts.
    """
    # Get recent job summaries (last 7 days) that haven't been processed
    week_ago = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=7)

    jobs = (
        await db.execute(
            select(Job).where(
                Job.organization_id == org_id,
                Job.status == "done",
                Job.updated_at >= week_ago,
                Job.result_summary.isnot(None),
            ).order_by(Job.updated_at.desc()).limit(100)
        )
    ).scalars().all()

    facts: list[BrainFact] = []
    for job in jobs:
        # Simple heuristic: lines with "X is Y" or "X = Y" patterns
        summary = job.result_summary or ""
        for line in summary.splitlines():
            line = line.strip()
            if not line:
                continue
            # Look for "is" pattern: "The renewal rate is 85%"
            if " is " in line and len(line) < 200:
                parts = line.split(" is ", 1)
                if len(parts) == 2:
                    key = parts[0].strip()[:200]
                    value = parts[1].strip()[:1000]
                    if len(key) > 5 and len(value) > 2:
                        facts.append(
                            BrainFact(
                                id=uuid4(),
                                organization_id=org_id,
                                scope="department",
                                scope_id=job.department_id,
                                key=key,
                                value=value,
                                confidence=0.7,
                                source_id=None,
                            )
                        )

    for fact in facts:
        db.add(fact)
    await db.flush()
    return facts


async def _extract_patterns(db: AsyncSession, org_id: UUID) -> list[dict]:
    """Extract procedural patterns from repeated successful tool sequences.

    For v1, we count tool call frequencies. Phase 5 will use sequence mining.
    """
    # Aggregate tool calls from audit_log
    rows = (
        await db.execute(
            text("""
                select
                  payload->>'tool' as tool_name,
                  count(*) as cnt
                from audit_log
                where organization_id = :org
                  and action = 'chat.tool_call'
                  and created_at >= now() - interval '7 days'
                group by payload->>'tool'
                having count(*) >= 3
                order by cnt desc
                limit 20
            """),
            {"org": str(org_id)},
        )
    ).mappings().all()

    patterns = [dict(r) for r in rows]
    log.info("extracted %d tool patterns for org=%s", len(patterns), org_id)
    return patterns


async def _summarize_old_episodes(db: AsyncSession, org_id: UUID) -> int:
    """Compress old chat turns (>30 days) into episode summaries.

    Returns the number of episodes summarized.
    """
    thirty_days_ago = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=30)

    # Find old chat_turn sources
    old_sources = (
        await db.execute(
            select(BrainSource).where(
                BrainSource.organization_id == org_id,
                BrainSource.kind == "chat_turn",
                BrainSource.created_at < thirty_days_ago,
            ).order_by(BrainSource.created_at.desc()).limit(50)
        )
    ).scalars().all()

    if not old_sources:
        return 0

    # Group by week and create summaries
    # For v1, we simply mark them as archived; Phase 5 will LLM-summarize.
    archived = 0
    for source in old_sources:
        source.kind = "chat_turn_archived"
        archived += 1

    await db.flush()
    log.info("archived %d old chat turns for org=%s", archived, org_id)
    return archived
