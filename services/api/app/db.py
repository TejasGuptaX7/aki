from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_for_org(org_id: UUID | None) -> AsyncIterator[AsyncSession]:
    """Yield a session with `app.org_id` set for RLS.

    All tenant-scoped queries inside this block see only rows for `org_id`.
    Unauthenticated requests pass None and get a session with no GUC set —
    those must only hit tables without RLS (e.g. waitlist).
    """
    async with SessionLocal() as session:
        if org_id is not None:
            await session.execute(
                text("SET LOCAL app.org_id = :oid"), {"oid": str(org_id)}
            )
        yield session
