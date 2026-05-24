"""Prometheus-compatible metrics endpoint.

Exposes key operational metrics for scraping by Prometheus or compatible
monitoring systems. Metrics are computed on-the-fly from the database.

Metrics exposed:
  - aki_org_total           — total organizations
  - aki_dept_total          — total departments
  - aki_jobs_total          — jobs by status
  - aki_cost_total          — cumulative cost USD
  - aki_chat_total          — total chat completions
  - aki_brain_chunks_total  — total brain chunks
  - aki_hermes_containers   — running hermes containers (from Redis registry)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from sqlalchemy import func, select, text

from app.db import SessionLocal

log = logging.getLogger(__name__)
router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus text format metrics."""
    lines: list[str] = []

    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))

        # Organizations
        org_count = (
            await db.execute(select(func.count()).select_from(text("organizations")))
        ).scalar_one()
        lines.append("# HELP aki_org_total Total organizations")
        lines.append("# TYPE aki_org_total gauge")
        lines.append(f"aki_org_total {org_count}")

        # Departments
        dept_count = (
            await db.execute(select(func.count()).select_from(text("departments")))
        ).scalar_one()
        lines.append("# HELP aki_dept_total Total departments")
        lines.append("# TYPE aki_dept_total gauge")
        lines.append(f"aki_dept_total {dept_count}")

        # Jobs by status
        job_counts = (await db.execute(text("""
                    select status, count(*) as cnt
                    from jobs
                    group by status
                """))).mappings().all()
        lines.append("# HELP aki_jobs_total Total jobs by status")
        lines.append("# TYPE aki_jobs_total gauge")
        for row in job_counts:
            lines.append(f'aki_jobs_total{{status="{row["status"]}"}} {row["cnt"]}')

        # Cumulative cost
        total_cost = (await db.execute(text("""
                    select coalesce(sum((payload->>'cost_usd')::numeric), 0)
                    from audit_log
                    where action in ('chat.complete', 'job.complete')
                """))).scalar_one()
        lines.append("# HELP aki_cost_total Cumulative cost USD")
        lines.append("# TYPE aki_cost_total counter")
        lines.append(f"aki_cost_total {float(total_cost or 0):.4f}")

        # Chat completions
        chat_count = (await db.execute(text("""
                    select count(*) from audit_log where action = 'chat.complete'
                """))).scalar_one()
        lines.append("# HELP aki_chat_total Total chat completions")
        lines.append("# TYPE aki_chat_total counter")
        lines.append(f"aki_chat_total {chat_count}")

        # Brain chunks
        chunk_count = (
            await db.execute(select(func.count()).select_from(text("brain_chunks")))
        ).scalar_one()
        lines.append("# HELP aki_brain_chunks_total Total brain chunks")
        lines.append("# TYPE aki_brain_chunks_total gauge")
        lines.append(f"aki_brain_chunks_total {chunk_count}")

    # Hermes containers from Redis
    try:
        import redis.asyncio as redis

        from app.config import get_settings

        settings = get_settings()
        r = redis.from_url(settings.redis_url, decode_responses=True)
        container_count = 0
        async for _ in r.scan_iter(match="hermes:registry:*"):
            container_count += 1
        await r.close()
        lines.append("# HELP aki_hermes_containers Running Hermes containers")
        lines.append("# TYPE aki_hermes_containers gauge")
        lines.append(f"aki_hermes_containers {container_count}")
    except Exception:
        pass

    return Response(content="\n".join(lines) + "\n", media_type="text/plain")
