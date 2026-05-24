"""Email and notification dispatch.

Uses Resend for transactional emails. Falls back to logging if Resend is not
configured. All notifications are fire-and-forget (queued via asyncio task).

Notification types:
  - spend_cap_soft     — daily spend approaching soft cap
  - spend_cap_hard     — daily spend exceeded hard cap (blocks further usage)
  - job_complete       — async job finished
  - org_invite         — new user invited to org
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
) -> dict[str, Any] | None:
    """Send an email via Resend. Returns the API response or None if not configured."""
    settings = get_settings()
    if not settings.resend_api_key or not settings.resend_from_address:
        log.debug("email skipped: resend not configured")
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.resend_from_address,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    "text": text or html,
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.exception("email send failed: %s", e)
        return None


def notify_spend_cap_soft(org_name: str, org_admin_email: str, current: float, cap: float) -> None:
    """Fire-and-forget soft cap warning."""
    subject = f"[{org_name}] Daily spend approaching cap"
    html = f"""
    <p>Your organization <strong>{org_name}</strong> has spent
    <strong>${current:.2f}</strong> today.</p>
    <p>The soft spend cap is <strong>${cap:.2f}</strong>.</p>
    <p>You can adjust this in your <a href="/admin/settings">admin settings</a>.</p>
    """
    asyncio.create_task(send_email(org_admin_email, subject, html))


def notify_spend_cap_hard(org_name: str, org_admin_email: str, current: float, cap: float) -> None:
    """Fire-and-forget hard cap alert."""
    subject = f"[{org_name}] Daily spend cap exceeded"
    html = f"""
    <p>Your organization <strong>{org_name}</strong> has exceeded its daily
    hard spend cap of <strong>${cap:.2f}</strong>.</p>
    <p>Current spend: <strong>${current:.2f}</strong>.</p>
    <p>New chat turns and jobs are temporarily blocked until the cap is
    increased or the next billing day begins.</p>
    <p><a href="/admin/settings">Adjust spend cap</a></p>
    """
    asyncio.create_task(send_email(org_admin_email, subject, html))


def notify_job_complete(
    org_name: str,
    recipient_email: str,
    job_brief: str,
    job_id: str,
    success: bool,
) -> None:
    """Fire-and-forget job completion notification."""
    status = "completed successfully" if success else "failed"
    subject = f"[{org_name}] Job {status}: {job_brief[:60]}"
    html = f"""
    <p>Your async job has <strong>{status}</strong>.</p>
    <p><strong>Brief:</strong> {job_brief}</p>
    <p><a href="/jobs/{job_id}">View details</a></p>
    """
    asyncio.create_task(send_email(recipient_email, subject, html))
