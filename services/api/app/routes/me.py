from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.middleware import get_principal, get_session
from app.models import Organization, User

router = APIRouter()


@router.get("/me")
async def me(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
) -> dict:
    user = (
        await db.execute(
            select(User).where(User.clerk_user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    org = (
        await db.execute(
            select(Organization).where(Organization.id == principal.organization_id)
        )
    ).scalar_one_or_none()
    return {
        "user": {"id": str(user.id), "email": user.email} if user else None,
        "organization": {"id": str(org.id), "name": org.name} if org else None,
    }
