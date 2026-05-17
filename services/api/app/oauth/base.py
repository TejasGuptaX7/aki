"""Shared scaffolding for native OAuth handlers.

Each provider module (gmail.py, slack.py, …) subclasses `OAuthHandler` and
fills in the per-provider bits (auth URL, token URL, scopes, tool list).
The base class implements the generic OAuth2 authorization-code flow with
PKCE optional and a `refresh_token` rotation rule that always replaces the
previously-stored refresh token with whatever the provider returns.

State token: HMAC over (org_id, agent_id, provider, nonce, expiry). The
HMAC key is the same `arcade_verifier_token` secret — single shared
"backend secret" env var keeps the .env minimal. State is opaque to the
frontend; we encode + verify in start_auth / handle_callback.

Token storage: we put `access_token`, `refresh_token`, `expires_at`,
`scope`, and provider-specific extras (like Slack's `team_id`) into
`Connection.config`. v1 stores plaintext — a follow-up will switch to
pgcrypto column-level encryption keyed off a service KMS. Don't add a
plaintext-vs-cipher branch yet; rotate once when we cut over.

Why no async refresh background job: we refresh-on-demand from
native_mcp.py just before each tool call (cheap; provider tokens last
hours). A scheduled refresher would be one more moving part.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import append_audit
from app.config import get_settings
from app.models import Connection


log = logging.getLogger(__name__)


# State TTL: 10 min is enough for the user to actually click through the
# consent screen, short enough that a leaked redirect URL goes stale fast.
STATE_TTL_SECONDS = 600


class NativeOAuthError(RuntimeError):
    def __init__(self, msg: str, *, status: int = 0, body: str = ""):
        super().__init__(msg)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class NativeToolSpec:
    """One MCP tool exposed by a native handler.

    `caller` is an async function that takes (args: dict, conn: Connection,
    db: AsyncSession) and returns a JSON-serializable result. It runs
    INSIDE the same request as the MCP call from Hermes — keep it short
    or the LB will time out.
    """
    name: str
    description: str
    input_schema: dict
    caller: Callable[[dict, Connection, AsyncSession], Awaitable[Any]]


# ── State token (HMAC) ──────────────────────────────────────────────────────


def _hmac_key() -> bytes:
    s = get_settings()
    if not s.arcade_verifier_token:
        # Without a secret we can't sign state and the OAuth flow is open
        # to CSRF. Refuse to issue auth URLs.
        raise NativeOAuthError(
            "ARCADE_VERIFIER_TOKEN not configured; "
            "native OAuth requires a backend secret to sign state tokens"
        )
    return s.arcade_verifier_token.encode("utf-8")


def encode_state(
    *,
    org_id: UUID,
    agent_id: UUID | None,
    provider: str,
) -> str:
    """Produce an opaque state token the provider will echo back. Carries
    (org, agent, provider, expiry, nonce) under HMAC-SHA256."""
    payload = {
        "o": str(org_id),
        "a": str(agent_id) if agent_id else None,
        "p": provider,
        "e": int(time.time()) + STATE_TTL_SECONDS,
        "n": uuid4().hex,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_hmac_key(), raw, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    )


def _b64ud(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def decode_state(state: str) -> dict[str, Any]:
    """Validate signature + expiry, return the payload dict.

    Raises NativeOAuthError on any mismatch. The control plane treats this
    as the sole source of truth for "which org/agent is finishing this
    OAuth dance" — never trust query params for those values."""
    try:
        raw_b64, sig_b64 = state.split(".", 1)
        raw = _b64ud(raw_b64)
        sig = _b64ud(sig_b64)
    except (ValueError, base64.binascii.Error) as e:
        raise NativeOAuthError(f"malformed state: {e}")

    expected = hmac.new(_hmac_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise NativeOAuthError("state signature mismatch")

    payload = json.loads(raw.decode("utf-8"))
    if payload.get("e", 0) < int(time.time()):
        raise NativeOAuthError("state expired")
    return payload


# ── OAuthHandler base class ─────────────────────────────────────────────────


class OAuthHandler(ABC):
    """Subclass interface for native providers.

    Concrete handlers set the class vars + provide a `tools()` method.
    """

    # Identifier we use in Connection.config.source ("gmail_native", …) and
    # in the URL: POST /connections/oauth/start?provider=<provider_slug>.
    provider_slug: str
    # The provider name we use in Connection.provider column (shorter; what
    # the UI displays).
    display_provider: str
    # OAuth2 endpoints.
    authorize_url: str
    token_url: str
    # Default scopes requested in the auth flow. Per-call override possible.
    default_scopes: list[str]
    # Some providers want scopes space-separated, others comma-separated.
    scope_delimiter: str = " "
    # If True, providers like Slack that pin the redirect URI per-app need
    # us to send `redirect_uri` again on the token exchange (most do).
    requires_redirect_on_exchange: bool = True
    # Extra parameters for the authorize URL (e.g. {"access_type": "offline",
    # "prompt": "consent"} for Google to force a refresh_token).
    extra_auth_params: dict[str, str] = {}
    # Audience field on the access token response payload — most providers
    # use "access_token" but a few stuff it under a different key.
    access_token_field: str = "access_token"

    # ── Required overrides ────────────────────────────────────────────────

    @abstractmethod
    def client_id(self) -> str | None: ...

    @abstractmethod
    def client_secret(self) -> str | None: ...

    @abstractmethod
    def tools(self) -> list[NativeToolSpec]:
        """MCP tools surfaced by this provider when connected. Returned
        list is the source of truth for native_mcp.py's `tools/list` reply.
        """

    # ── Hooks (override if the provider deviates) ─────────────────────────

    def post_token_exchange(self, token_response: dict) -> dict:
        """Massage the token response before storing. Override for providers
        that nest tokens inside non-standard fields (e.g. Slack puts the bot
        token under `access_token` but also returns `authed_user.access_token`
        for user-scoped calls)."""
        return token_response

    def redirect_uri(self) -> str:
        """One callback URL for every provider, derived from web_base_url.
        The frontend page at /connect/oauth/callback reads ?code=&state= and
        POSTs to /connections/oauth/callback."""
        return f"{get_settings().web_base_url.rstrip('/')}/connect/oauth/callback"

    # ── Public flow methods ───────────────────────────────────────────────

    async def start_auth(
        self,
        *,
        org_id: UUID,
        agent_id: UUID | None,
        db: AsyncSession,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build the consent URL. Records `oauth.start` to the audit log."""
        cid = self.client_id()
        if not cid:
            raise NativeOAuthError(
                f"{self.provider_slug} OAuth client_id not configured"
            )

        state = encode_state(
            org_id=org_id, agent_id=agent_id, provider=self.provider_slug
        )
        scope = self.scope_delimiter.join(scopes or self.default_scopes)

        from urllib.parse import urlencode

        params: dict[str, str] = {
            "client_id": cid,
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": scope,
            "state": state,
            **self.extra_auth_params,
        }
        auth_url = f"{self.authorize_url}?{urlencode(params)}"

        await append_audit(
            db,
            org_id,
            actor=f"user:{org_id}",  # caller may overwrite with the real Clerk sub
            action="oauth.start",
            target=self.provider_slug,
            payload={"agent_id": str(agent_id) if agent_id else None},
            agent_id=agent_id,
        )
        return {"auth_url": auth_url, "state": state}

    async def handle_callback(
        self,
        *,
        code: str,
        state: str,
        db: AsyncSession,
    ) -> Connection:
        """Exchange code for tokens, upsert a Connection row, return it.

        Validates the state token before touching the provider. The
        principal context comes from the state's payload — DO NOT trust
        any other source for org_id here, since the callback route is the
        OAuth provider redirecting the user's browser and they haven't
        re-authenticated to us yet.
        """
        payload = decode_state(state)
        org_id = UUID(payload["o"])
        agent_id = UUID(payload["a"]) if payload.get("a") else None

        cid = self.client_id()
        secret = self.client_secret()
        if not cid or not secret:
            raise NativeOAuthError(
                f"{self.provider_slug} OAuth credentials missing at callback"
            )

        token_body: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cid,
            "client_secret": secret,
        }
        if self.requires_redirect_on_exchange:
            token_body["redirect_uri"] = self.redirect_uri()

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
            r = await c.post(
                self.token_url,
                data=token_body,
                headers={"Accept": "application/json"},
            )
        if r.status_code >= 400:
            raise NativeOAuthError(
                f"{self.provider_slug} token exchange failed",
                status=r.status_code,
                body=r.text[:500],
            )
        try:
            tok = r.json()
        except json.JSONDecodeError as e:
            raise NativeOAuthError(
                f"{self.provider_slug} token response not JSON: {e}",
                body=r.text[:500],
            )

        # Some providers (Slack) return 200 with `{"ok": false, "error": …}`.
        if tok.get("ok") is False:
            raise NativeOAuthError(
                f"{self.provider_slug} token exchange refused",
                body=str(tok)[:500],
            )

        tok = self.post_token_exchange(tok)
        return await self._upsert_connection(
            db=db,
            org_id=org_id,
            agent_id=agent_id,
            token=tok,
        )

    async def refresh_token(
        self, connection: Connection, db: AsyncSession
    ) -> Connection:
        """Refresh the access token if expired or within 60s of expiry.
        Rotates refresh_token if the provider returns a new one.

        Returns the connection (mutated in place). Caller is responsible
        for `await db.commit()`.
        """
        cfg = dict(connection.config or {})
        refresh = cfg.get("refresh_token")
        expires_at = cfg.get("expires_at")  # epoch seconds
        if not refresh:
            # Some providers (Slack) issue non-expiring tokens; nothing to do.
            return connection
        if expires_at and float(expires_at) - 60 > time.time():
            return connection

        cid = self.client_id()
        secret = self.client_secret()
        if not cid or not secret:
            raise NativeOAuthError(
                f"{self.provider_slug} OAuth credentials missing on refresh"
            )

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
            r = await c.post(
                self.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": cid,
                    "client_secret": secret,
                },
                headers={"Accept": "application/json"},
            )
        if r.status_code >= 400:
            raise NativeOAuthError(
                f"{self.provider_slug} refresh failed",
                status=r.status_code,
                body=r.text[:500],
            )
        new = r.json()
        if new.get("ok") is False:
            raise NativeOAuthError(
                f"{self.provider_slug} refresh refused",
                body=str(new)[:500],
            )

        cfg["access_token"] = new.get(self.access_token_field) or new.get("access_token")
        # Refresh-token rotation: replace if the provider issued a new one,
        # keep the old one otherwise (Google rotates only on `prompt=consent`
        # cycles, Slack doesn't refresh-rotate, etc).
        if new.get("refresh_token"):
            cfg["refresh_token"] = new["refresh_token"]
        if new.get("expires_in"):
            cfg["expires_at"] = int(time.time()) + int(new["expires_in"])
        connection.config = cfg

        await append_audit(
            db,
            connection.organization_id,
            actor=f"oauth:{self.provider_slug}",
            action="oauth.refresh",
            target=str(connection.id),
            payload={"provider": self.display_provider},
            agent_id=connection.agent_id,
        )
        return connection

    # ── Internal: write the Connection row ────────────────────────────────

    async def _upsert_connection(
        self,
        *,
        db: AsyncSession,
        org_id: UUID,
        agent_id: UUID | None,
        token: dict,
    ) -> Connection:
        access_token = token.get(self.access_token_field) or token.get("access_token")
        if not access_token:
            raise NativeOAuthError(
                f"{self.provider_slug} token response missing access token",
                body=str(token)[:500],
            )

        cfg: dict[str, Any] = {
            "source": f"{self.provider_slug}_native",
            "access_token": access_token,
            "refresh_token": token.get("refresh_token"),
            "scope": token.get("scope"),
        }
        if token.get("expires_in"):
            cfg["expires_at"] = int(time.time()) + int(token["expires_in"])
        # Stash provider-specific extras so handlers can pull them later
        # (Slack: team_id, bot_user_id; HubSpot: hub_id; Linear: workspace_id).
        for k in (
            "team", "team_id", "authed_user",
            "bot_user_id", "app_id",
            "workspace_id", "workspace_name",
            "hub_id", "hub_domain",
            "bot_id", "owner",
        ):
            if k in token:
                cfg[k] = token[k]

        # External-account-id: use whatever the provider gives us; falls
        # back to a synthesized one so the column stays non-null when the
        # provider doesn't return an obvious id.
        ext = (
            (token.get("authed_user") or {}).get("id")
            or token.get("team_id")
            or token.get("workspace_id")
            or token.get("hub_id")
            or (token.get("owner") or {}).get("user")
            or f"{self.provider_slug}-{uuid4().hex[:12]}"
        )

        # Replace existing row for the same (org, agent, provider) tuple if
        # any — the user is reconnecting (probably after revoking access).
        from sqlalchemy import and_

        agent_filter = (
            Connection.agent_id.is_(None) if agent_id is None
            else Connection.agent_id == agent_id
        )
        existing = await db.scalar(
            select(Connection).where(
                and_(
                    Connection.organization_id == org_id,
                    Connection.provider == self.display_provider,
                    agent_filter,
                )
            )
        )
        if existing is not None:
            existing.config = cfg
            existing.external_account_id = str(ext)
            existing.scopes = (token.get("scope") or "").split(self.scope_delimiter)
            existing.status = "active"
            row = existing
        else:
            row = Connection(
                id=uuid4(),
                organization_id=org_id,
                agent_id=agent_id,
                provider=self.display_provider,
                external_account_id=str(ext),
                scopes=(token.get("scope") or "").split(self.scope_delimiter),
                config=cfg,
                status="active",
            )
            db.add(row)

        await append_audit(
            db,
            org_id,
            actor=f"oauth:{self.provider_slug}",
            action="oauth.callback",
            target=self.provider_slug,
            payload={
                "agent_id": str(agent_id) if agent_id else None,
                "external_account_id": str(ext),
            },
            agent_id=agent_id,
        )
        await db.execute(
            text("SELECT pg_notify('org_connections_changed', :oid)"),
            {"oid": str(org_id)},
        )
        return row


# ── Registry ────────────────────────────────────────────────────────────────


NATIVE_HANDLERS: dict[str, OAuthHandler] = {}


def _register(handler: OAuthHandler) -> None:
    NATIVE_HANDLERS[handler.provider_slug] = handler


def get_handler(provider: str) -> OAuthHandler:
    h = NATIVE_HANDLERS.get(provider)
    if h is None:
        raise NativeOAuthError(f"no native OAuth handler for provider={provider}")
    return h


# Provider modules call _register() at import time. The package
# `__init__.py` imports each handler module after `base` finishes loading,
# which populates NATIVE_HANDLERS without a circular import.
