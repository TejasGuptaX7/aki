"""Thin Clerk Backend API client.

Only the calls our backend actually needs. Auth = Bearer ${CLERK_SECRET_KEY}.
Docs: https://clerk.com/docs/reference/backend-api
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
_BASE = "https://api.clerk.com/v1"


def _settings_or_raise():
    s = get_settings()
    if not s.clerk_secret_key:
        raise RuntimeError("CLERK_SECRET_KEY not configured")
    return s


async def update_user_public_metadata(clerk_user_id: str, patch: dict[str, Any]) -> None:
    """Merge `patch` into the user's public_metadata.

    Used at org-provision time to populate user.public_metadata.aki_org_id
    so the `aki` JWT template can fill the org_id claim on next sign-in.
    """
    s = _settings_or_raise()
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.patch(
            f"{_BASE}/users/{clerk_user_id}/metadata",
            headers={
                "Authorization": f"Bearer {s.clerk_secret_key}",
                "Content-Type": "application/json",
            },
            json={"public_metadata": patch},
        )
        if r.status_code >= 400:
            log.warning(
                "clerk metadata update failed user=%s status=%s body=%s",
                clerk_user_id,
                r.status_code,
                r.text[:300],
            )
            r.raise_for_status()
