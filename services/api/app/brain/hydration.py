"""Brain hydration for Hermes turns.

Every chat completion and every async job brief is pre-hydrated with relevant
context from the Brain (shared memory). After the turn completes, the full
conversation is persisted back into Brain so future turns can cite it.

This module is the "spine" of the three-product architecture: it ensures that
both Hermes (cloud) and Aki (desktop) share context through Brain.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.chunker import chunk_text
from app.brain.embeddings import embed
from app.brain.retrieval import retrieve
from app.config import get_settings
from app.models import BrainChunk, BrainSource

log = logging.getLogger(__name__)


_BRAIN_CONTEXT_PROMPT = """\
The following information from your organization's knowledge base may be
relevant to the current request. Cite sources when you use them.

{context}
"""

_MAX_BRAIN_CONTEXT_TOKENS = 2_000  # ~8000 chars, leaves room for conversation


async def hydrate_messages(
    db: AsyncSession,
    org_id: UUID,
    dept_id: UUID,
    user_id: str,
    messages: list[dict[str, Any]],
    *,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Prepend Brain-retrieved context to the messages list.

    1. Extract the latest user message as the query.
    2. Retrieve top-k relevant chunks from Brain (hybrid search + ACL).
    3. Format as a context block and inject into the system message.
    4. Return the augmented messages list.
    """
    from app.feature_flags import is_enabled

    if not await is_enabled("brain_hydration", org_id):
        return messages

    # Extract the most recent user message as the retrieval query
    query = ""
    for m in reversed(messages):
        if (m or {}).get("role") == "user":
            content = m.get("content") or ""
            if isinstance(content, str):
                query = content
            elif isinstance(content, list):
                # Vision / multi-modal: extract text parts
                query = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            break

    if not query.strip():
        return messages

    principals = [str(org_id), str(dept_id), user_id]
    try:
        hits = await retrieve(
            db,
            org_id=org_id,
            query=query,
            principals=principals,
            k=k,
            scope_filter=None,  # Allow cross-scope retrieval (org + dept + user)
        )
    except Exception:
        log.exception("brain retrieval failed for query; continuing without context")
        return messages

    if not hits:
        return messages

    # Format hits into a context block, staying within token budget
    context_parts: list[str] = []
    current_len = 0
    max_chars = _MAX_BRAIN_CONTEXT_TOKENS * 4  # rough heuristic

    for i, hit in enumerate(hits, 1):
        kind = hit.provenance.get("kind", "unknown")
        origin = hit.provenance.get("origin", "unknown")
        part = f"[{i}] Source: {hit.title} ({kind}, {origin})\n{hit.content}\n"
        if current_len + len(part) > max_chars:
            break
        context_parts.append(part)
        current_len += len(part)

    if not context_parts:
        return messages

    context_block = _BRAIN_CONTEXT_PROMPT.format(context="\n".join(context_parts))

    # Inject into system message, or create one if absent
    new_messages = list(messages)
    system_idx = None
    for i, m in enumerate(new_messages):
        if (m or {}).get("role") == "system":
            system_idx = i
            break

    if system_idx is not None:
        existing = str(new_messages[system_idx].get("content", ""))
        new_messages[system_idx] = {
            "role": "system",
            "content": f"{existing}\n\n{context_block}",
        }
    else:
        new_messages.insert(0, {"role": "system", "content": context_block})

    return new_messages


async def persist_turn(
    db: AsyncSession,
    org_id: UUID,
    dept_id: UUID,
    user_id: str,
    *,
    kind: str,  # "chat_turn" | "job_turn" | "tool_result"
    user_text: str,
    assistant_text: str,
    title: str | None = None,
    uri: str | None = None,
    origin: str = "hermes",
) -> UUID | None:
    """Persist a conversation turn into Brain as a source + chunks.

    Returns the BrainSource id, or None if nothing to persist.
    """
    from app.audit import append_audit

    settings = get_settings()
    body = f"USER:\n{user_text}\n\nASSISTANT:\n{assistant_text}"

    if not body.strip():
        return None

    source_title = title or (user_text.strip().splitlines()[0][:200] or "turn")

    source = BrainSource(
        organization_id=org_id,
        scope="department",
        scope_id=dept_id,
        kind=kind,
        origin=origin,
        uri=uri,
        title=source_title,
        acl_principals=[str(org_id), str(dept_id), user_id],
    )
    db.add(source)
    await db.flush()

    chunks = chunk_text(
        body,
        target_tokens=settings.brain_chunk_tokens,
        overlap_chars=settings.brain_chunk_overlap,
    )
    if chunks:
        try:
            embeddings = await embed([c.content for c in chunks])
        except Exception:
            log.exception("embed failed for turn; storing source w/o chunks")
            return source.id
        for chunk, vec in zip(chunks, embeddings, strict=False):
            db.add(
                BrainChunk(
                    source_id=source.id,
                    organization_id=org_id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding=vec,
                )
            )

    await append_audit(
        db,
        org_id,
        actor=user_id,
        action="brain.ingest",
        target=str(source.id),
        payload={
            "kind": kind,
            "origin": origin,
            "uri": uri,
            "chunks": len(chunks),
            "title": source_title,
        },
    )
    return source.id
