"""Rate limiter wiring — Redis-backed with per-org isolation.

Production deploys should use the Redis storage backend so limits hold across
workers. We also support per-organization rate limiting so one tenant cannot
exhaust the shared API capacity.

Usage:
    from app.limits import limiter, org_limiter

    @router.post("/v1/chat/completions")
    @limiter.limit("120/minute")              # global IP limit
    @org_limiter.limit("60/minute")           # per-org limit
    async def chat_completions(...):
        ...
"""

from __future__ import annotations

import logging

import redis.asyncio as redis
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

log = logging.getLogger(__name__)


# Global IP-based limiter (dev fallback to in-memory)
limiter = Limiter(key_func=get_remote_address)


def _get_org_id(request: Request) -> str:
    """Extract org_id from the authenticated principal for per-org limiting."""
    principal = getattr(request.state, "principal", None)
    if principal is not None and hasattr(principal, "organization_id"):
        return str(principal.organization_id)
    # Fallback to IP if unauthenticated
    return get_remote_address(request)


# Per-organization limiter — keyed by org_id, not IP
org_limiter = Limiter(key_func=_get_org_id)


async def configure_limiters() -> None:
    """Swap to Redis storage if REDIS_URL is available. Called once at startup."""
    settings = get_settings()
    try:
        r = redis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()

        # Redis is available — reconfigure both limiters. Our minimal
        # RedisStorage doesn't formally inherit from limits' Storage base
        # because it only implements the slice of the interface slowapi
        # actually calls (incr); structural duck-typing matches at runtime.
        limiter._storage = RedisStorage(r, prefix="rl:global")  # type: ignore[assignment]
        org_limiter._storage = RedisStorage(r, prefix="rl:org")  # type: ignore[assignment]
        log.info("rate limiting configured with Redis backend")
    except Exception:
        log.warning(
            "Redis unavailable for rate limiting — falling back to in-memory "
            "(limits will NOT be shared across workers)"
        )


class RedisStorage:
    """Minimal Redis storage adapter for slowapi.

    slowapi's built-in RedisStorage requires redis-py < 4.0 in some versions.
    This adapter uses the modern redis.asyncio client.
    """

    def __init__(self, client: redis.Redis, prefix: str = "rl") -> None:
        self.client = client
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def incr(self, key: str, expiry: int) -> int:
        """Synchronous incr — slowapi calls this synchronously."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._aincr(key, expiry))
        except RuntimeError:
            # No event loop — use a thread pool (last resort)
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self._aincr(key, expiry)).result()

    async def _aincr(self, key: str, expiry: int) -> int:
        k = self._key(key)
        pipe = self.client.pipeline()
        pipe.incr(k)
        pipe.expire(k, expiry)
        results = await pipe.execute()
        return results[0]

    def get(self, key: str) -> int:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._aget(key))
        except RuntimeError:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self._aget(key)).result()

    async def _aget(self, key: str) -> int:
        val = await self.client.get(self._key(key))
        return int(val) if val is not None else 0
