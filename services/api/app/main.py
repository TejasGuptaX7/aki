import asyncio
import contextlib
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.agent_runtime import hibernation_loop, reap_orphans, shutdown_all
from app.config import get_settings
from app.limits import limiter
from app.routes import (
    audit, billing, brain, chat, connections, departments, devices,
    health, jobs, me, webhooks,
)
from app.scheduler import scheduler_loop

settings = get_settings()
log = logging.getLogger("hermes")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: reap orphaned containers from any previous crashed run.
    Background: hibernate idle per-org Hermes containers.
    Shutdown: stop everything tracked."""
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
app.include_router(billing.router)
