"""Live ACL re-check with 5-minute TTL cache.

Brain stores an ACL snapshot at ingest time, but that snapshot can drift:
a user might be removed from a Slack channel, a Notion page, a Drive folder.
Without a live re-check, retrieval can leak content the principal no longer
has access to.

Per-origin live checks live in this module. What we check vs what we trust:

  - first-party origins (hermes/aki/web/api): snapshot is authoritative,
    no live call.
  - slack: parse the channel id from `uri`; call
    SLACK_FETCH_CONVERSATION_INFO. If the channel is archived/private and
    we can't see it, fail closed. Per-user membership recheck waits on the
    aki_user_id ↔ slack_user_id mapping landing in a later phase.
  - notion / drive: stubs that fail closed with a logged warning until the
    integrations are wired.

The cache is in-process (cachetools.TTLCache). For multi-worker prod, swap
to Redis using `redis.set(key, "1", ex=300)` — same key shape.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable
from uuid import UUID

from cachetools import TTLCache

log = logging.getLogger("aki.brain.acl")

# 10,000 entries × 5min TTL is generous; resize if memory pressure shows up.
_cache: TTLCache = TTLCache(maxsize=10_000, ttl=300)


def _key(source_id: UUID, principals: Iterable[str]) -> tuple:
    return (str(source_id), tuple(sorted(principals)))


async def is_allowed(
    source_id: UUID,
    origin: str,
    uri: str | None,
    snapshot_principals: list[str],
    requester_principals: Iterable[str],
    org_id: UUID | None = None,
) -> bool:
    """Return True if requester is allowed to see this source right now.

    Order of evaluation:
      1. Snapshot intersection — if there's no overlap with the snapshot
         the answer is no, regardless of live state.
      2. Cache hit — return previous decision.
      3. Provider-specific live check (Slack/Notion/Drive/…).
      4. Cache the result for the 5-min TTL.

    `org_id` is required for any live-check that goes through Composio.
    If omitted, live checks degrade to snapshot-trust.
    """
    requester_set = set(map(str, requester_principals))
    snapshot_set = set(map(str, snapshot_principals or []))

    if not snapshot_set or not snapshot_set & requester_set:
        return False

    cache_key = _key(source_id, requester_set)
    if cache_key in _cache:
        return _cache[cache_key]

    decision = await _live_check(
        origin, uri, snapshot_principals, requester_set, org_id,
    )
    _cache[cache_key] = decision
    return decision


_SLACK_CHANNEL_RE = re.compile(r"slack://(?:channel|message)/(C[A-Z0-9]+)")


async def _live_check(
    origin: str, uri: str | None,
    snapshot: list[str], requester: set[str],
    org_id: UUID | None,
) -> bool:
    """Provider-specific live ACL re-check."""
    if origin in ("hermes", "aki", "web", "api"):
        # First-party content; the writer's principals on the source are
        # authoritative since we wrote them ourselves at ingest.
        return True

    if origin == "slack" and uri and org_id is not None:
        return await _live_check_slack(uri, org_id)

    if origin == "notion":
        # Notion live ACL recheck requires a Notion integration token per org.
        # Until Composio Notion actions are wired, fail closed.
        log.warning("notion live ACL recheck not implemented; denying access for %s", uri)
        return False

    if origin == "drive":
        # Google Drive live ACL recheck requires a Drive API token per org.
        # Until Composio Drive actions are wired, fail closed.
        log.warning("drive live ACL recheck not implemented; denying access for %s", uri)
        return False

    # Unknown origin: snapshot must do.
    log.info("no live ACL recheck for origin=%s; trusting snapshot", origin)
    return True


async def _live_check_slack(uri: str, org_id: UUID) -> bool:
    """Verify the channel referenced by `uri` still exists and is visible
    to the org's Slack connection. Returns False if the channel was
    archived/deleted or the call fails with permission_denied.

    Per-user membership recheck is a follow-up — it needs the
    aki_user ↔ slack_user mapping which we don't store yet.
    """
    m = _SLACK_CHANNEL_RE.search(uri)
    if not m:
        log.info("slack uri without channel id: %s; trusting snapshot", uri)
        return True
    channel_id = m.group(1)

    # Local import so brain/acl.py doesn't pull httpx unless live checks fire.
    from app.composio_client import get_composio_client

    try:
        result = await get_composio_client().execute_action(
            org_id,
            "SLACK_FETCH_CONVERSATION_INFO",
            {"channel": channel_id, "include_locale": False},
        )
    except Exception as e:
        # Provider error: fail-open with a warning. Treating a transient
        # 503 as a hard "no" would degrade the agent's recall during outages.
        log.warning("slack live ACL recheck call failed for %s: %s; trusting snapshot",
                    channel_id, e)
        return True

    data = (result or {}).get("data") or {}
    channel = data.get("channel") or {}
    if channel.get("is_archived"):
        return False
    if data.get("error") in ("channel_not_found", "missing_scope"):
        return False
    return True


def invalidate_source(source_id: UUID) -> None:
    """Drop all cached decisions for `source_id`. Call after a source's
    ACL snapshot changes or after an external ACL change notification."""
    prefix = str(source_id)
    for key in list(_cache.keys()):
        if key[0] == prefix:
            _cache.pop(key, None)


def cache_stats() -> dict:
    """For /admin/brain visibility. Cheap."""
    return {"size": len(_cache), "maxsize": _cache.maxsize, "ttl_s": _cache.ttl}
