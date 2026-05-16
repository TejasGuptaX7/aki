from fastapi import FastAPI

from app.config import get_settings
from app.routes import health, me

settings = get_settings()

app = FastAPI(
    title="Aki API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "prod" else None,
)

app.include_router(health.router)
app.include_router(me.router)
