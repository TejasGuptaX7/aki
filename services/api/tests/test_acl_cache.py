"""ACL recheck behavior. Pure-ish — only the `cachetools` dep beyond stdlib."""
import asyncio
from uuid import uuid4

from app.brain.acl import is_allowed, invalidate_source


def test_snapshot_intersection_required():
    src = uuid4()
    # No overlap → False, no live check needed.
    allowed = asyncio.run(is_allowed(
        src, origin="hermes", uri=None,
        snapshot_principals=["alice", "bob"],
        requester_principals={"carol"},
    ))
    assert allowed is False


def test_first_party_origin_trusts_snapshot():
    src = uuid4()
    allowed = asyncio.run(is_allowed(
        src, origin="hermes", uri=None,
        snapshot_principals=["alice"],
        requester_principals={"alice"},
    ))
    assert allowed is True


def test_unknown_origin_fails_open_with_snapshot():
    src = uuid4()
    allowed = asyncio.run(is_allowed(
        src, origin="some-new-saas", uri="x",
        snapshot_principals=["alice"],
        requester_principals={"alice"},
    ))
    assert allowed is True


def test_invalidate_drops_cache():
    src = uuid4()
    asyncio.run(is_allowed(src, origin="hermes", uri=None,
                           snapshot_principals=["alice"],
                           requester_principals={"alice"}))
    invalidate_source(src)
    # We can't assert internal state easily; just confirm no crash and the
    # next call still returns the same answer.
    again = asyncio.run(is_allowed(src, origin="hermes", uri=None,
                                    snapshot_principals=["alice"],
                                    requester_principals={"alice"}))
    assert again is True
