"""Request-scoped session with RLS GUC set from the verified principal.

``get_principal`` resolves the JWT (Clerk or device) into a ``Principal``
that carries cached role information (highest role, per-department role map,
and ``is_org_admin``) so downstream RBAC checks are O(1) with no extra DB
round-trips.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, verify
from app.db import session_for_org


async def get_principal(request: Request) -> Principal:
    """Verify the request and return a fully-populated ``Principal``."""
    return await verify(request)


async def get_session(
    principal: Principal = Depends(get_principal),
) -> AsyncIterator[AsyncSession]:
    async with session_for_org(principal.organization_id) as session:
        yield session
