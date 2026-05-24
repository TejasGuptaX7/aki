"""Data retention policy enforcement.

Automatically deletes or archives data older than the organization's configured
retention period. Runs as a nightly scheduler tick.

Tables affected:
  - audit_log (> retention days)
  - brain_chunks / brain_sources (> retention days)
  - job_events / jobs (> retention days)
  - aki_devices (revoked + > retention days)

Deletion is hard (irreversible). In a future phase we may archive to cold
storage (S3) before deletion.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


_DEFAULT_RETENTION_DAYS = 365


async def enforce_retention(db: AsyncSession, org_id: UUID) -> dict:
    """Apply data retention policy for one organization.

    Returns a summary of rows deleted per table.
    """
    # Read org retention setting
    row = await db.execute(
        text("""
            select settings->>'data_retention_days' as retention
            from organizations
            where id = :org
        """),
        {"org": str(org_id)},
    )
    result = row.scalar_one_or_none()
    retention_days = int(result) if result else _DEFAULT_RETENTION_DAYS

    if retention_days <= 0:
        return {"retention_days": retention_days, "deleted": {}}

    deleted: dict[str, int] = {}

    tables = [
        ("audit_log", "created_at"),
        ("job_events", "ts"),
        ("brain_chunks", "created_at"),
    ]

    for table, ts_col in tables:
        try:
            r = await db.execute(
                text(f"""
                    delete from {table}
                    where organization_id = :org
                      and {ts_col} < now() - (:days * interval '1 day')
                """),
                {"org": str(org_id), "days": retention_days},
            )
            deleted[table] = r.rowcount
        except Exception as e:
            log.warning("retention delete failed for %s org=%s: %s", table, org_id, e)

    # Delete old jobs (and their events via cascade if configured)
    try:
        r = await db.execute(
            text("""
                delete from jobs
                where organization_id = :org
                  and status in ('done', 'failed', 'cancelled')
                  and updated_at < now() - (:days * interval '1 day')
            """),
            {"org": str(org_id), "days": retention_days},
        )
        deleted["jobs"] = r.rowcount
    except Exception as e:
        log.warning("retention delete failed for jobs org=%s: %s", org_id, e)

    # Delete old brain_sources that no longer have chunks
    try:
        r = await db.execute(
            text("""
                delete from brain_sources s
                where s.organization_id = :org
                  and s.created_at < now() - (:days * interval '1 day')
                  and not exists (
                      select 1 from brain_chunks c where c.source_id = s.id
                  )
            """),
            {"org": str(org_id), "days": retention_days},
        )
        deleted["brain_sources"] = r.rowcount
    except Exception as e:
        log.warning("retention delete failed for brain_sources org=%s: %s", org_id, e)

    log.info("retention enforced for org=%s days=%s deleted=%s", org_id, retention_days, deleted)
    return {"retention_days": retention_days, "deleted": deleted}


async def retention_tick() -> int:
    """Run retention enforcement for all organizations.

    Returns the number of orgs processed.
    """
    from app.db import SessionLocal

    processed = 0
    async with SessionLocal() as db:
        await db.execute(text("SET LOCAL row_security = off"))
        orgs = (await db.execute(text("select id from organizations"))).scalars().all()

        for org_id in orgs:
            try:
                await enforce_retention(db, org_id)
                processed += 1
            except Exception:
                log.exception("retention enforcement failed for org=%s", org_id)

        await db.commit()
    return processed
