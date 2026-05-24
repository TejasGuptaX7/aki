"""Health and readiness probes.

Kubernetes / container orchestrators use these to determine whether the pod
should receive traffic (readiness) and whether it should be restarted (liveness).
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings

log = logging.getLogger(__name__)
router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health() -> dict:
    """Liveness probe — lightweight, always returns 200 if the process is up."""
    return {"ok": True, "uptime_s": int(time.time() - _start_time)}


@router.get("/ready")
async def ready() -> Response:
    """Readiness probe — checks downstream dependencies before accepting traffic.

    Returns 200 only if Postgres and Redis are reachable.
    """
    checks: dict[str, bool] = {}

    # Postgres check
    try:
        from app.db import SessionLocal

        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as e:
        log.warning("readiness: postgres check failed: %s", e)
        checks["postgres"] = False

    # Redis check
    try:
        import redis.asyncio as redis

        settings = get_settings()
        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.close()
        checks["redis"] = True
    except Exception as e:
        log.warning("readiness: redis check failed: %s", e)
        checks["redis"] = False

    all_ok = all(checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse

    return JSONResponse(
        content={"ready": all_ok, "checks": checks},
        status_code=status_code,
    )
