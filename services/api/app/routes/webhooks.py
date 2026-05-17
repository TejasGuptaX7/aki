"""Inbound webhooks.

POST /webhooks/clerk — Clerk fires this on user.created, user.updated, etc.
The handler is the *one* place an org, its first user, and the org's default
"Aki" agent are provisioned together — same transaction, idempotent on
clerk_user_id so replays are safe.

Verified via svix (Clerk uses Svix for webhook signing).
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from svix.webhooks import Webhook, WebhookVerificationError

from app.clerk_client import update_user_public_metadata
from app.config import get_settings
from app.db import session_for_org, SessionLocal
from app.limits import limiter
from app.models import Agent, AgentMemory, Organization, User
from app.rate_limits import check_global_circuit_breaker
from app.routes.agents import DEFAULT_SYSTEM_PROMPT


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

        # Global circuit breaker: if the platform is over today's spend cap,
        # refuse new signups. svix will retry the webhook; when we're back
        # under-budget, the retry succeeds and the user is provisioned.
        # Existing users keep working — only NEW orgs get gated.
        await check_global_circuit_breaker(db)

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

        # Every org gets a default agent named "Aki" so the chat surface is
        # usable from the first sign-in. The user can rename it, create more,
        # or delete it later (as long as one active agent remains).
        default_agent = Agent(
            id=uuid4(),
            organization_id=org.id,
            name="Aki",
            slug="aki",
            system_prompt=DEFAULT_SYSTEM_PROMPT.format(name="Aki"),
            status="active",
        )
        db.add(default_agent)
        await db.flush()

        db.add(
            AgentMemory(
                id=uuid4(),
                organization_id=org.id,
                agent_id=default_agent.id,
                key="onboarding",
                value=f"Org created for {email} on signup.",
            )
        )
        await db.commit()

    # No external-provider entity provisioning at signup. Native OAuth
    # (app/oauth/) and Arcade both create their identity lazily on the
    # first /connections/oauth/start (or /connections/arcade/start), using
    # our org_id (or org_id:agent_id for per-agent) as the user id.

    # Push the new org_id into Clerk's user.public_metadata so the JWT
    # template's {{user.public_metadata.aki_org_id}} resolves on next sign-in.
    # If this fails the user can still sign in — they just won't have an
    # org_id claim and /me will 403 until we retry. Not fatal at signup.
    if settings.clerk_secret_key:
        try:
            await update_user_public_metadata(
                clerk_user_id, {"aki_org_id": str(org.id)}
            )
        except Exception:
            log.exception(
                "clerk metadata update failed for user=%s org=%s — JWT will "
                "lack org_id claim until retry", clerk_user_id, org.id,
            )
