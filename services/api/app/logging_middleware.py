"""Structured request/response logging middleware.

Logs every HTTP request with timing, status, and principal info.
In production, these logs feed into centralized logging (Datadog, Splunk, etc.)
for debugging, audit, and compliance.

Logs include:
  - request_id (for distributed tracing)
  - method, path, query_string
  - principal (user_id, org_id)
  - status_code, response_time_ms
  - user_agent, client_ip
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = logging.getLogger("aki.access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Logs every request with structured fields."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._log(
                request=request,
                status_code=500,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        self._log(
            request=request,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        return response

    def _log(
        self,
        request: Request,
        status_code: int,
        elapsed_ms: float,
        error: str | None = None,
    ) -> None:
        rid = getattr(request.state, "request_id", "-")
        principal = getattr(request.state, "principal", None)
        user_id = principal.user_id if principal else "-"
        org_id = str(principal.organization_id) if principal else "-"

        extra = {
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params) if request.query_params else "",
            "status_code": status_code,
            "elapsed_ms": round(elapsed_ms, 2),
            "user_id": user_id,
            "org_id": org_id,
            "client_ip": request.client.host if request.client else "-",
            "user_agent": request.headers.get("user-agent", "-"),
        }
        if error:
            extra["error"] = error

        log.info("%(method)s %(path)s %(status_code)s %(elapsed_ms)sms", extra, extra=extra)
