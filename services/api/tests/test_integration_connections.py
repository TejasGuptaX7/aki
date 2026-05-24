"""Department_id resolution for connections.

Verifies _default_department_id returns the principal's first department
or falls back to querying the org's first department.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.auth import Principal
from app.routes.connections import _default_department_id, _default_department_id_for_org
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


async def test_default_department_id_returns_principal_first_department():
    """When principal has departments, return the first one with no DB query."""
    dept_ids = [uuid4(), uuid4()]
    principal = Principal(
        user_id="user_1",
        organization_id=uuid4(),
        department_ids=dept_ids,
        role="member",
    )
    mock_db = AsyncMock()
    result = await _default_department_id(mock_db, principal)
    assert result == dept_ids[0]
    mock_db.execute.assert_not_awaited()


async def test_default_department_id_falls_back_to_org_query():
    """When principal has no departments, query the org's first department."""
    org_id = uuid4()
    first_dept = uuid4()
    principal = Principal(
        user_id="user_1",
        organization_id=org_id,
        department_ids=[],
        role="member",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = first_dept

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    result = await _default_department_id(mock_db, principal)
    assert result == first_dept

    # Verify the call was made with an org-scoped query
    call_args = mock_db.execute.await_args
    stmt = call_args[0][0]  # first positional arg
    assert "Department" in str(stmt) or "departments" in str(stmt).lower()


async def test_default_department_id_raises_when_no_departments_exist():
    """If the org has zero departments, raise 400."""
    org_id = uuid4()
    principal = Principal(
        user_id="user_1",
        organization_id=org_id,
        department_ids=[],
        role="member",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await _default_department_id(mock_db, principal)
    assert exc_info.value.status_code == 400
    assert "no departments exist" in exc_info.value.detail.lower()


async def test_default_department_id_for_org_returns_first_department():
    """_default_department_id_for_org queries by org_id directly."""
    org_id = uuid4()
    first_dept = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = first_dept

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    result = await _default_department_id_for_org(mock_db, org_id)
    assert result == first_dept


async def test_default_department_id_for_org_raises_when_empty():
    """_default_department_id_for_org raises 400 when org has no departments."""
    org_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await _default_department_id_for_org(mock_db, org_id)
    assert exc_info.value.status_code == 400
    assert "no departments exist" in exc_info.value.detail.lower()
