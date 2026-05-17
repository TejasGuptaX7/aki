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
    # URL the Hermes container uses to reach the control plane. Different
    # from api_base_url because the container's `localhost` is itself, not
    # the host. On Mac dev: http://host.docker.internal:8000. On Fly: the
    # internal hostname (e.g. http://aki-api.internal:8000).
    api_internal_url: str = "http://host.docker.internal:8000"
    web_base_url: str = "http://localhost:3000"   # for OAuth callback redirects

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
    clerk_secret_key: str | None = None       # for Backend API calls (metadata update)

    # Agent
    hermes_gateway_url: str = "http://localhost:8080"
    hermes_api_key: str | None = None
    # Per-org workspace root. Default lives in $HOME so it works on a Mac dev
    # box; production deploys override to /var/lib/aki/hermes or similar.
    hermes_data_dir: str = "~/.aki/hermes"
    hermes_idle_minutes: int = 15
    agent_runtime: Literal["local", "railway", "modal"] = "local"
    hermes_model_provider: str = "custom"   # Hermes 0.13 'provider' name
    hermes_model_name: str = "gpt-5"

    # Redis (per-org lifecycle locks, NOTIFY fan-out cache)
    redis_url: str = "redis://localhost:6379/0"

    # Model providers
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536

    # Connectors — Pipedream Connect (primary long-tail API layer).
    # client_credentials OAuth: backend exchanges (client_id, client_secret)
    # at /v1/oauth/token for a short-lived JWT, then uses Bearer + X-PD-Environment
    # on every Connect API call.
    pipedream_project_id: str | None = None         # proj_xxxxx
    pipedream_client_id: str | None = None
    pipedream_client_secret: str | None = None
    pipedream_environment: Literal["development", "production"] = "development"
    pipedream_base_url: str = "https://api.pipedream.com"

    # Connectors — Arcade (first-class agent-auth for top-20 tools).
    arcade_api_key: str | None = None
    arcade_base_url: str = "https://api.arcade.dev"

    # Connectors — self-hosted browser harness (services/browser-harness).
    # See services/browser-harness/PROTOCOL.md for the wire contract.
    browser_harness_url: str | None = None          # http://browser-harness.aki.internal:7900
    browser_harness_api_key: str | None = None

    # Connectors — Browser Use Cloud (kept for fallback / deterministic ops).
    browser_use_api_key: str | None = None
    browser_use_mcp_base_url: str = "https://api.browser-use.com"

    # Slack — the Aki app (registered at api.slack.com).
    # While Pipedream Connect free tier doesn't support white-label OAuth,
    # we use a direct bot token: install Aki to a workspace via api.slack.com
    # → copy the Bot User OAuth Token → paste here. Same model as a
    # single-tenant Slack bot. When we eventually flip to Pipedream Business
    # + custom OAuth apps, this stops being a single token and becomes a
    # per-org connection.config.bot_token (Pipedream-managed).
    slack_signing_secret: str | None = None         # for /webhooks/slack verification
    slack_bot_token: str | None = None              # xoxb-… for direct chat.postMessage
    slack_client_id: str | None = None
    slack_app_id: str | None = None

    # Rate limits — per-org daily caps and the platform-wide circuit breaker.
    # The product is free during beta; without billing we need these to
    # prevent a single abuser from burning weeks of credits in one weekend.
    rate_limit_daily_actions: int = 500             # agent chat actions / day / org
    rate_limit_daily_browser_seconds: int = 3600    # browser harness seconds / day / org
    rate_limit_daily_llm_cents: int = 5000          # LLM spend cents / day / org ($50)
    platform_daily_spend_cap_cents: int = 50_000    # total platform $/day before pausing signups ($500)


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
