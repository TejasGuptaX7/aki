"""Integration: cost_caps reads from organizations.settings and enforces
hard/soft caps correctly.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import cost_caps
from app.cost_caps import check_spend_cap, enforce_spend_cap

def test_cost_caps_queries_organizations_table():
    """Ensure the SQL in check_spend_cap targets organizations.settings."""
    source = inspect.getsource(check_spend_cap)
    assert "organizations" in source
    assert "org_memory" not in source


@pytest.mark.asyncio
async def test_enforce_spend_cap_hard_blocks(monkeypatch):
    """When projected spend exceeds hard cap, enforce_spend_cap raises 402."""
    org_id = uuid4()

    async def fake_check(*args, **kwargs):
        return False, "Daily spend cap exceeded: $110.00 / $100.00. Contact your org admin."

    monkeypatch.setattr(cost_caps, "check_spend_cap", fake_check)

    mock_db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await enforce_spend_cap(mock_db, org_id, estimated_cost=10.0)
    assert exc_info.value.status_code == 402
    assert "cap exceeded" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_enforce_spend_cap_soft_allows(monkeypatch):
    """When only soft cap is exceeded, enforce_spend_cap does NOT raise."""
    org_id = uuid4()

    async def fake_check(*args, **kwargs):
        return True, "Warning: daily spend approaching soft cap ($90.00 / $80.00)"

    monkeypatch.setattr(cost_caps, "check_spend_cap", fake_check)

    mock_db = AsyncMock()
    # Should not raise
    await enforce_spend_cap(mock_db, org_id, estimated_cost=5.0)


@pytest.mark.asyncio
async def test_enforce_spend_cap_no_caps(monkeypatch):
    """When no caps are configured, enforce_spend_cap is a no-op."""
    org_id = uuid4()

    async def fake_check(*args, **kwargs):
        return True, ""

    monkeypatch.setattr(cost_caps, "check_spend_cap", fake_check)

    mock_db = AsyncMock()
    await enforce_spend_cap(mock_db, org_id)
