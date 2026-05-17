"""Native OAuth handlers for the top-5 high-value providers.

We own the full OAuth dance for these so we don't depend on any connector
platform's roadmap, branding, or pricing for what matters most:

  gmail   — read/send mail, list threads, fetch single message
  slack   — post to channels, list channels
  notion  — list/search pages, read content
  linear  — list issues, comment, transition state
  hubspot — list contacts/deals, create contact

Public surface (all providers expose the same shape — see app/oauth/base.py
for the Protocol):

  start_auth(principal, agent_id) -> {auth_url, state}
  handle_callback(code, state, db) -> Connection row
  refresh_token(connection, db) -> Connection row (mutated in place)
  tools() -> list[NativeToolSpec]

Tool execution is wired through app/routes/native_mcp.py — a Streamable
HTTP MCP server hermes connects to per-org, alongside `request_approval`.

Why native and not Arcade for these five: each one is on the critical path
for the agent product. If Arcade has an outage, or deprecates a tool, or
the consent screen starts looking off, we can't be blocked. The other ~30
SaaS we'd otherwise need are nice-to-have and fine via Arcade.
"""
from __future__ import annotations

from app.oauth.base import (
    NATIVE_HANDLERS,
    NativeOAuthError,
    NativeToolSpec,
    OAuthHandler,
    get_handler,
)

# Import handler modules so each one calls _register() at import time.
# Order doesn't matter; the registry is keyed by provider_slug.
from app.oauth import gmail as _gmail   # noqa: E402,F401
from app.oauth import slack as _slack   # noqa: E402,F401
from app.oauth import notion as _notion # noqa: E402,F401
from app.oauth import linear as _linear # noqa: E402,F401
from app.oauth import hubspot as _hubspot # noqa: E402,F401

__all__ = [
    "NATIVE_HANDLERS",
    "NativeOAuthError",
    "NativeToolSpec",
    "OAuthHandler",
    "get_handler",
]
