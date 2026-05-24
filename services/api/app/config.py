from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"  # for OAuth callback redirects

    # Safety: the X-Dev-Org-Id auth bypass requires BOTH app_env=dev AND this
    # flag set to true. Two checks so a single env misconfiguration in prod
    # doesn't let anyone claim any org.
    allow_dev_auth_bypass: bool = False

    # CORS — list of allowed origins. Defaults to empty (no browser clients).
    # Set CORS_ORIGINS="http://localhost:3000,https://app.aki.dev" in env.
    # NoDecode prevents pydantic-settings from JSON-decoding the env value
    # before our field_validator splits the CSV.
    cors_origins: Annotated[list[str], NoDecode] = []

    # Rate limits expressed in slowapi syntax (e.g. "60/minute", "10/second").
    rate_limit_webhooks: str = "120/minute"
    rate_limit_oauth: str = "30/minute"

    # Max request body for /webhooks/* in bytes.
    webhook_max_body_bytes: int = 1_048_576  # 1 MiB

    # Database — async URL for the app, sync URL for Alembic.
    database_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/aki")
    database_url_sync: str = Field(default="postgresql://postgres:postgres@localhost:5432/aki")

    # Clerk
    clerk_jwt_issuer: str | None = None
    clerk_jwks_url: str | None = None
    clerk_webhook_secret: str | None = None
    clerk_secret_key: str | None = None  # for Backend API calls (metadata update)

    # Agent
    hermes_gateway_url: str = "http://localhost:8080"
    hermes_api_key: str | None = None
    # Per-org workspace root. Default lives in $HOME so it works on a Mac dev
    # box; production deploys override to /var/lib/aki/hermes or similar.
    hermes_data_dir: str = "~/.aki/hermes"
    hermes_idle_minutes: int = 15
    agent_runtime: Literal["local", "railway", "modal"] = "local"
    hermes_model_provider: str = "custom"  # Hermes 0.13 'provider' name
    hermes_model_name: str = "gpt-5"

    # Redis (per-org lifecycle locks, NOTIFY fan-out cache)
    redis_url: str = "redis://localhost:6379/0"

    # Model providers
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536

    # Connectors
    composio_api_key: str | None = None
    composio_base_url: str = "https://backend.composio.dev"
    composio_webhook_secret: str | None = None
    composio_gmail_auth_config_id: str | None = None
    composio_slack_auth_config_id: str | None = None
    composio_slackbot_auth_config_id: str | None = None

    # Browser Use Cloud — long-tail no-API tools.
    browser_use_api_key: str | None = None
    browser_use_mcp_base_url: str = "https://api.browser-use.com"

    # Brain
    brain_chunk_tokens: int = 800  # approx tokens per chunk
    brain_chunk_overlap: int = 100  # chars carried into the next chunk

    # Aki desktop device JWTs (Ed25519). PEM-encoded private key; pyjwt
    # uses it for signing AND verification (it derives the pubkey from a
    # private PEM). Generate with:
    #   ssh-keygen -t ed25519 -m PEM -f device-jwt-key -N ""
    # then base64-encode contents of `device-jwt-key` and paste into env.
    device_jwt_signing_key: str | None = None

    # Stripe metering (Phase 5). Until these are set, /v1/billing/rollup
    # returns the computed totals but doesn't push to Stripe.
    stripe_secret_key: str | None = None
    stripe_meter_event_name: str | None = None
    stripe_customer_id: str | None = None

    # Resend (transactional email)
    resend_api_key: str | None = None
    resend_from_address: str | None = None

    # OpenTelemetry observability
    otlp_endpoint: str | None = None  # e.g. "http://localhost:4318/v1/traces"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_csv(cls, v):
        # Allow CORS_ORIGINS as either JSON list or simple "a,b,c" string.
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
