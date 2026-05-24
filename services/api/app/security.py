"""Security middleware and utilities.

Enforces security headers, input sanitization, and other defense-in-depth
measures required for enterprise deployments.
"""
from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # XSS protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Strict transport security (only in prod)
        from app.config import get_settings
        if get_settings().app_env == "prod":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


def sanitize_input(text: str, max_length: int = 10000) -> str:
    """Basic input sanitization to prevent injection attacks.

    Removes null bytes and truncates to max_length.
    """
    if not text:
        return ""
    # Remove null bytes
    text = text.replace("\x00", "")
    # Truncate
    return text[:max_length]
