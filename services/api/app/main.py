import asyncio
import contextlib
import logging
import sys
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.agent_runtime import hibernation_loop, reap_orphans, shutdown_all
from app.config import get_settings
from app.limits import limiter, configure_limiters
from app.logging_middleware import AccessLogMiddleware
from app.security import SecurityHeadersMiddleware
from app.telemetry import init_telemetry


def _configure_logging() -> None:
    """Structured JSON logging for production; pretty text for dev."""
    settings = get_settings()
    try:
        import structlog
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ExtraAdder(),
        ]
        if settings.app_env == "prod":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=True))
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        # Replace stdlib logging handlers too
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=logging.INFO if settings.app_env == "prod" else logging.DEBUG,
        )
    except ImportError:
        # structlog not installed — fall back to plain stdlib
        logging.basicConfig(
            level=logging.INFO if settings.app_env == "prod" else logging.DEBUG,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


_configure_logging()
from app.routes import (
    admin, audit, billing, brain, chat, connections, departments, devices,
    gdpr, health, jobs, me, metrics, webhooks,
)
from app.scheduler import scheduler_loop

settings = get_settings()
log = logging.getLogger("hermes")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: reap orphaned containers, init telemetry, configure rate limits.
    Background: hibernate idle per-org Hermes containers.
    Shutdown: stop everything tracked."""
    # Initialize observability
    try:
        init_telemetry()
    except Exception:
        log.exception("telemetry init failed (continuing startup)")

    # Configure rate limiting backend
    try:
        await configure_limiters()
    except Exception:
        log.exception("rate limiter config failed (continuing startup)")

    try:
        n = await reap_orphans()
        if n:
            log.info("reaped %d orphaned hermes container(s) on startup", n)
    except Exception:
        log.exception("reap_orphans failed (continuing startup)")

    hib_task = asyncio.create_task(hibernation_loop())
    sched_task = asyncio.create_task(scheduler_loop())
    try:
        yield
    finally:
        for t in (hib_task, sched_task):
            t.cancel()
        for t in (hib_task, sched_task):
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await shutdown_all()


app = FastAPI(
    title="Hermes API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "prod" else None,
    redoc_url="/redoc" if settings.app_env != "prod" else None,
    lifespan=lifespan,
)

# Rate limiting (slowapi)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Structured access logging
app.add_middleware(AccessLogMiddleware)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# CORS — empty list means no browser clients (curl/SDK only).
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a per-request id to every response for traceability."""
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return JSON (not text/plain) on unhandled errors, with request_id so
    clients and the server logs can be correlated."""
    rid = getattr(request.state, "request_id", "unknown")
    log.exception("unhandled exception request_id=%s", rid)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "request_id": rid},
    )


app.include_router(health.router)
app.include_router(me.router)
app.include_router(webhooks.router)
app.include_router(connections.router)
app.include_router(chat.router)
app.include_router(audit.router)
app.include_router(brain.router)
app.include_router(devices.router)
app.include_router(departments.router)
app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(gdpr.router)
app.include_router(metrics.router)
