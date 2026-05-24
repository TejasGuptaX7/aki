"""Feature flags for gradual rollouts and A/B testing.

Flags are stored in Redis with org-scoped overrides. Default values are
hardcoded here for safety (if Redis is down, features fall back to sensible
defaults).

Usage:
    from app.feature_flags import is_enabled

    if await is_enabled("brain_hydration", org_id="uuid"):
        ...
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from app.config import get_settings

log = logging.getLogger(__name__)

# Global defaults — these are the safe fallbacks.
_DEFAULTS: dict[str, bool] = {
    "brain_hydration": True,
    "cross_encoder_rerank": False,
    "cost_caps": True,
    "memory_consolidation": True,
    "data_retention": True,
    "slack_delivery": True,
    "email_notifications": False,
    "custom_model_training": False,
    "multi_org": False,
    "self_hosted": False,
}

_REDIS_PREFIX = "ff"
_CACHE_TTL_S = 300


async def _redis() -> redis.Redis | None:
    try:
        settings = get_settings()
        return redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


def _key(flag: str, org_id: UUID | str | None = None) -> str:
    if org_id:
        return f"{_REDIS_PREFIX}:{org_id}:{flag}"
    return f"{_REDIS_PREFIX}:global:{flag}"


async def is_enabled(flag: str, org_id: UUID | str | None = None) -> bool:
    """Check if a feature flag is enabled.

    Resolution order:
      1. Org-specific override in Redis
      2. Global override in Redis
      3. Hardcoded default
    """
    r = await _redis()
    if r is not None:
        try:
            # Check org-specific first
            if org_id:
                val = await r.get(_key(flag, org_id))
                if val is not None:
                    return val.lower() == "true"
            # Fall back to global
            val = await r.get(_key(flag))
            if val is not None:
                return val.lower() == "true"
        except Exception:
            pass

    return _DEFAULTS.get(flag, False)


async def set_flag(
    flag: str,
    value: bool,
    org_id: UUID | str | None = None,
) -> None:
    """Set a feature flag override in Redis."""
    r = await _redis()
    if r is None:
        raise RuntimeError("Redis unavailable; cannot set feature flag")
    await r.setex(_key(flag, org_id), _CACHE_TTL_S, "true" if value else "false")


async def get_all_flags(org_id: UUID | str | None = None) -> dict[str, bool]:
    """Return all flags resolved for the given org."""
    result = dict(_DEFAULTS)
    r = await _redis()
    if r is not None:
        try:
            # Global overrides
            for flag in _DEFAULTS:
                val = await r.get(_key(flag))
                if val is not None:
                    result[flag] = val.lower() == "true"
            # Org overrides
            if org_id:
                for flag in _DEFAULTS:
                    val = await r.get(_key(flag, org_id))
                    if val is not None:
                        result[flag] = val.lower() == "true"
        except Exception:
            pass
    return result
