from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    api_base_url: str = "http://localhost:8000"

    # Database — async URL for the app, sync URL for Alembic.
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aki"
    )
    database_url_sync: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/aki"
    )

    # Clerk
    clerk_jwt_issuer: str | None = None
    clerk_jwks_url: str | None = None
    clerk_webhook_secret: str | None = None

    # Agent
    hermes_gateway_url: str = "http://localhost:8080"
    hermes_api_key: str | None = None

    # Model providers
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536

    # Connectors
    composio_api_key: str | None = None
    composio_base_url: str = "https://backend.composio.dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
