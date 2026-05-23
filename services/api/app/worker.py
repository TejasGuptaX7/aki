"""arq worker — dispatches queued jobs against per-(org, dept) Hermes.

Lifecycle of a job, in code:

  1. POST /v1/jobs creates a row with status='queued' and enqueues a task
     named `dispatch_job` carrying just `(job_id, org_id)`.
  2. The arq worker picks up the task, opens a session scoped to org_id
     (RLS GUC), and re-reads the job row. Idempotent: re-running on a
     `done`/`cancelled` row is a no-op.
  3. Mark `status='running'`, cold-start the per-dept Hermes container,
     and issue ONE chat-completion turn with the brief as the user
     message + a worker system prompt.
  4. Stream the SSE response: every `event: hermes.tool.progress` becomes
     a `job_events(kind='tool_call')` row; assistant text deltas become
     `kind='chunk'` rows; final `usage` becomes `kind='status_change'`.
  5. On success: persist `result_summary`, write a `brain_sources` row
     of kind 'job_summary' (Brain becomes the long-term memory of every
     job the org ever ran), update `cost_usd`, mark `status='done'`.
  6. On failure: mark `status='failed'`, write the error into job_events.

Cron jobs (where `schedule_cron is not null`) are picked up by the
scheduler in `app/scheduler.py`, which sets `next_run_at` ahead and
re-enqueues via `dispatch_job`.

This module exists as a separate process: `python -m arq app.worker.Settings`.
The API process imports `enqueue_job` as a side-channel into the queue.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

import httpx

from app.brain.chunker import chunk_text
from app.config import get_settings
# Heavy deps (sqlalchemy, arq, internal models) are imported lazily inside
# the functions that use them so the SSE parser stays unit-testable
# without the full prod dep set.


log = logging.getLogger("aki.worker")


WORKER_SYSTEM_PROMPT = """\
You are Hermes, executing an asynchronous brief for a department of a
company. The employee who submitted this brief is OFFLINE — there is no
human to ask follow-up questions of in real time.

Operating principles:
- Make best-effort progress on the brief end-to-end.
- When you face a clarifying question, document the assumption you made
  and proceed; surface it in your final summary.
- Use available tools (Composio, Browser Use, custom MCP) freely. Cite
  what you used.
- End with a concise summary the employee can read tomorrow morning: what
  you did, what you assumed, what's still open, and any artifacts (URLs,
  ticket ids) they should follow up on.
"""


async def enqueue_job(job_id: UUID, org_id: UUID) -> None:
    """Side-channel from the API process: drop a job onto the arq queue."""
    from arq import create_pool
    settings = get_settings()
    redis = await create_pool(_redis_settings_from(settings.redis_url))
    try:
        await redis.enqueue_job("dispatch_job", str(job_id), str(org_id))
    finally:
        await redis.close()


def _redis_settings_from(url: str):
    """Parse REDIS_URL into arq's RedisSettings shape."""
    from arq.connections import RedisSettings
    from urllib.parse import urlparse
    p = urlparse(url)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        password=p.password,
        database=int((p.path or "/0").lstrip("/") or "0"),
    )


# ── arq task ──────────────────────────────────────────────────────────────

async def dispatch_job(ctx: dict, job_id_str: str, org_id_str: str) -> dict:
    """The arq task that actually runs a queued job."""
    from sqlalchemy import select, text
    from app.audit import append_audit
    from app.db import session_for_org
    from app.models import Job, JobEvent
    from app.pricing import estimate_cost_usd

    job_id = UUID(job_id_str)
    org_id = UUID(org_id_str)

    async with session_for_org(org_id) as db:
        job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            log.warning("dispatch_job: job %s not found (deleted?)", job_id)
            return {"status": "missing"}
        if job.status in ("done", "cancelled"):
            log.info("dispatch_job: job %s already %s, skipping", job_id, job.status)
            return {"status": "noop", "prior_status": job.status}

        # Optimistic claim: set running. If somebody else already claimed,
        # this UPDATE updates 0 rows and we exit.
        result = await db.execute(
            text("""
                update jobs set status = 'running', updated_at = now()
                where id = :id and status in ('queued', 'failed', 'waiting_human')
            """),
            {"id": str(job_id)},
        )
        if result.rowcount == 0:
            await db.commit()
            log.info("dispatch_job: job %s already claimed by another worker", job_id)
            return {"status": "raced"}

        await _log_event(db, job_id, "status_change", {"to": "running"})
        await db.commit()

    # Run the heavy lifting outside the session so we don't hold a DB
    # connection across the long Hermes turn.
    try:
        summary, usage, events = await _run_brief(job_id, org_id, job.department_id,
                                                  job.brief)
    except Exception as e:
        log.exception("job %s failed", job_id)
        async with session_for_org(org_id) as db:
            await db.execute(
                text("""
                    update jobs set status='failed', updated_at=now() where id=:id
                """),
                {"id": str(job_id)},
            )
            await _log_event(db, job_id, "error", {"message": str(e)[:512]})
            await append_audit(
                db, org_id, actor="worker:arq", action="job.failed",
                target=str(job_id), payload={"error": str(e)[:512]},
            )
            await db.commit()
        return {"status": "failed", "error": str(e)[:256]}

    settings = get_settings()
    cost_usd = estimate_cost_usd(
        settings.hermes_model_name,
        int((usage or {}).get("prompt_tokens") or 0),
        int((usage or {}).get("completion_tokens") or 0),
    )

    async with session_for_org(org_id) as db:
        # Write the job summary into Brain so future retrieval can cite it.
        brain_id = await _write_summary_to_brain(
            db, org_id, job.department_id, job_id, job.actor, job.brief, summary,
        )

        await db.execute(
            text("""
                update jobs
                set status = 'done', result_summary = :summary,
                    cost_usd = :cost, brain_source_id = :bid, updated_at = now()
                where id = :id
            """),
            {
                "id": str(job_id),
                "summary": summary[:65_000],
                "cost": cost_usd,
                "bid": str(brain_id) if brain_id else None,
            },
        )
        await _log_event(db, job_id, "status_change", {
            "to": "done", "cost_usd": cost_usd, "tool_calls": len(events),
        })
        await append_audit(
            db, org_id, actor="worker:arq", action="job.complete",
            target=str(job_id),
            payload={"cost_usd": cost_usd, "tool_calls": len(events),
                     "brain_source_id": str(brain_id) if brain_id else None},
        )
        await db.commit()

    # Best-effort delivery: if the dept has a slack channel configured, ask
    # Hermes to post the summary there. Free audit (Hermes' MCP call lands
    # in chat.tool_call rows) and no duplicate Slack-client code.
    try:
        await _deliver_to_slack(org_id, job.department_id, job_id, summary)
    except Exception:
        log.exception("slack delivery failed for job %s", job_id)

    return {"status": "done", "cost_usd": cost_usd, "tool_calls": len(events)}


async def _deliver_to_slack(
    org_id: UUID, dept_id: UUID, job_id: UUID, summary: str,
) -> None:
    """Post a follow-up turn telling Hermes to publish the summary in
    `notification_config.slack_channel`. No-op if the channel isn't set
    or the summary is empty.

    The turn is issued directly against Hermes' OpenAI-compat API (not via
    /v1/chat/completions), so we tap the SSE here to record tool calls
    into job_events ourselves — otherwise the Slack post would be invisible.
    """
    import json as _json
    from sqlalchemy import select
    from app.agent_runtime import ensure_running
    from app.audit import append_audit
    from app.db import session_for_org
    from app.models import Department

    if not summary.strip():
        return

    async with session_for_org(org_id) as db:
        dept = (
            await db.execute(select(Department).where(Department.id == dept_id))
        ).scalar_one_or_none()
    if dept is None:
        return

    channel = (dept.notification_config or {}).get("slack_channel")
    if not channel:
        return

    async with session_for_org(org_id) as db:
        proc = await ensure_running(db, org_id, dept_id)

    body_text = (
        f"Post this job summary to {channel} using the `slackbot` toolkit. "
        f"If the bot isn't in the channel, follow the bot-identity flow in "
        f"your system prompt rather than guessing.\n\n"
        f"--- summary ---\n{summary[:8_000]}\n---"
    )
    payload = {
        "model": get_settings().hermes_model_name,
        "stream": True,
        "messages": [{"role": "user", "content": body_text}],
    }
    body = _json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {proc.api_key}",
        "Content-Type": "application/json",
    }

    tool_events: list[dict] = []
    tail = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as c:
        async with c.stream(
            "POST", f"{proc.base_url}/v1/chat/completions",
            content=body, headers=headers,
        ) as upstream:
            async for raw in upstream.aiter_bytes():
                try:
                    tail += raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
                blocks, tail = _parse_sse_blocks(tail)
                for event, data in blocks:
                    if data == "[DONE]":
                        continue
                    try:
                        obj = _json.loads(data)
                    except Exception:
                        continue
                    if event and event.startswith("hermes.tool"):
                        tool_events.append(obj)

    async with session_for_org(org_id) as db:
        await _log_event(db, job_id, "delivery", {
            "channel": channel, "tool_calls": len(tool_events),
        })
        await append_audit(
            db, org_id, actor="worker:arq", action="job.deliver",
            target=str(job_id),
            payload={"channel": channel, "tool_calls": len(tool_events)},
        )
        await db.commit()


async def _run_brief(
    job_id: UUID, org_id: UUID, dept_id: UUID, brief: str,
) -> tuple[str, dict[str, Any] | None, list[dict]]:
    """Cold-start the per-dept Hermes container and issue one chat turn.

    Returns (assistant_text, usage_dict, tool_events). The assistant text is
    accumulated from streaming delta chunks; we don't rely on Hermes to
    return a non-stream variant.
    """
    from app.agent_runtime import ensure_running
    from app.db import session_for_org
    from app.models import JobEvent

    async with session_for_org(org_id) as db:
        proc = await ensure_running(db, org_id, dept_id)

    payload = {
        "model": get_settings().hermes_model_name,
        "stream": True,
        "messages": [
            {"role": "system", "content": WORKER_SYSTEM_PROMPT},
            {"role": "user", "content": brief},
        ],
    }
    body = json.dumps(payload).encode()
    headers = {
        "Authorization": f"Bearer {proc.api_key}",
        "Content-Type": "application/json",
    }

    chunks_text: list[str] = []
    tool_events: list[dict] = []
    final_usage: dict | None = None
    tail = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=10.0)) as c:
        async with c.stream(
            "POST", f"{proc.base_url}/v1/chat/completions",
            content=body, headers=headers,
        ) as upstream:
            async for raw in upstream.aiter_bytes():
                try:
                    tail += raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
                blocks, tail = _parse_sse_blocks(tail)
                for event, data in blocks:
                    if data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    if event and event.startswith("hermes.tool"):
                        tool_events.append(obj)
                        from app.db import session_for_org as _sfo
                        async with _sfo(org_id) as db:
                            await _log_event(db, job_id, "tool_call", obj)
                            await db.commit()
                        continue
                    if isinstance(obj, dict):
                        # Extract assistant text from OpenAI-shape chunks.
                        for choice in obj.get("choices") or []:
                            delta = (choice.get("delta") or {})
                            piece = delta.get("content") or ""
                            if piece:
                                chunks_text.append(piece)
                        if "usage" in obj and obj["usage"]:
                            final_usage = obj["usage"]

    return "".join(chunks_text).strip(), final_usage, tool_events


def _parse_sse_blocks(buf: str):
    """Same shape as routes/chat.py's parser. Yields (event, data_str)."""
    blocks: list[tuple[str | None, str]] = []
    pos = 0
    while True:
        sep = buf.find("\n\n", pos)
        if sep == -1:
            return blocks, buf[pos:]
        block = buf[pos:sep]
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


async def _log_event(db, job_id: UUID, kind: str, payload: dict) -> None:
    from app.models import JobEvent
    db.add(JobEvent(job_id=job_id, kind=kind, payload=payload))
    await db.flush()


async def _write_summary_to_brain(
    db, org_id: UUID, dept_id: UUID, job_id: UUID, actor: str,
    brief: str, summary: str,
) -> UUID | None:
    """Index the job's brief + summary into Brain so future jobs can cite it."""
    from app.audit import append_audit
    from app.brain.embeddings import embed
    from app.models import BrainChunk, BrainSource

    if not summary.strip():
        return None
    settings = get_settings()

    # Title = first line of the brief, truncated. Provenance carried in `uri`.
    title = brief.strip().splitlines()[0][:200]
    body = f"BRIEF:\n{brief}\n\nRESULT:\n{summary}"

    source = BrainSource(
        organization_id=org_id,
        scope="department",
        scope_id=dept_id,
        kind="job_summary",
        origin="hermes",
        uri=f"job://{job_id}",
        title=title,
        acl_principals=[str(org_id), str(dept_id), actor],
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
            log.exception("embed failed for job %s; storing source w/o chunks", job_id)
            return source.id
        for chunk, vec in zip(chunks, embeddings):
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
        db, org_id, actor="worker:arq", action="brain.ingest",
        target=str(source.id),
        payload={"kind": "job_summary", "origin": "hermes",
                 "uri": f"job://{job_id}", "chunks": len(chunks),
                 "title": title},
    )
    return source.id


# ── arq settings entrypoint (`python -m arq app.worker.Settings`) ─────────


def _build_settings():
    """Build the arq WorkerSettings on demand. Used by `python -m arq`."""
    class Settings:
        functions = [dispatch_job]
        redis_settings = _redis_settings_from(get_settings().redis_url)
    return Settings


# arq's CLI accepts `module.path.Settings`. Resolve it lazily so importing
# this module doesn't require arq to be installed (handy for unit tests).
def __getattr__(name):
    if name == "Settings":
        return _build_settings()
    raise AttributeError(name)
