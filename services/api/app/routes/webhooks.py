"""Inbound webhooks.

POST /webhooks/clerk — Clerk fires this on user.created, user.updated, etc.
The handler is the *one* place an org and its first user are provisioned
together: same transaction, plus a default org_memory row and a Composio
entity. Idempotent on clerk_user_id so replays are safe.

Verified via svix (Clerk uses Svix for webhook signing).
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import get_settings
from app.db import session_for_org, SessionLocal
from app.limits import limiter
from app.models import Organization, OrgMemory, User


log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _domain_from_email(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else email


@router.post("/clerk", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(lambda: get_settings().rate_limit_webhooks)
async def clerk_webhook(request: Request) -> None:
    settings = get_settings()
    if not settings.clerk_webhook_secret:
        raise HTTPException(503, "CLERK_WEBHOOK_SECRET not configured")

    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(413, "webhook body too large")
    try:
        evt = Webhook(settings.clerk_webhook_secret).verify(
            body, dict(request.headers)
        )
    except WebhookVerificationError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"bad signature: {e}")

    if evt.get("type") != "user.created":
        return

    data = evt["data"]
    clerk_user_id = data["id"]
    primary = data.get("primary_email_address_id")
    email = next(
        (
            e["email_address"]
            for e in data.get("email_addresses", [])
            if e["id"] == primary
        ),
        None,
    ) or (data.get("email_addresses", [{}])[0].get("email_address"))

    if not email:
        raise HTTPException(400, "no email on user payload")

    # No GUC set here — we're creating the org row itself, before any RLS
    # context exists. Provisioning queries hit organizations (no RLS) and
    # users (RLS-enabled, but we set the GUC mid-transaction).
    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(User).where(User.clerk_user_id == clerk_user_id)
            )
        ).scalar_one_or_none()
        if existing:
            return  # idempotent replay

        org = Organization(id=uuid4(), name=_domain_from_email(email))
        db.add(org)
        await db.flush()

        # Now set the org GUC so the next inserts pass RLS.
        # SET LOCAL doesn't accept bound params; set_config() does.
        from sqlalchemy import text
        await db.execute(
            text("SELECT set_config('app.org_id', :oid, true)"),
            {"oid": str(org.id)},
        )

        user = User(
            id=uuid4(),
            clerk_user_id=clerk_user_id,
            email=email,
            organization_id=org.id,
        )
        db.add(user)
        db.add(
            OrgMemory(
                id=uuid4(),
                organization_id=org.id,
                key="onboarding",
                value=f"Org created for {email} on signup.",
            )
        )
        await db.commit()

    # No Composio entity provisioning here — in v3 the entity is created
    # implicitly when we first call composio.create(userId) (i.e. when the
    # org's Hermes runtime materializes its MCP session, or when the first
    # OAuth is initiated). org.id is the entity_id either way.
