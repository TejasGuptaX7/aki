"""Per-agent service tokens for the internal MCP auth path.

Hermes profiles call back to the control plane to run tools that require
DB writes / org context (today: `request_approval`; in future: memory
sync, audit lookups, etc.). Those calls authenticate with a per-agent
service token sent as `Authorization: Bearer <token>`.

Storage model:
  - Plaintext lives only in the per-agent workspace's `config.yaml` on the
    host volume (mode 0600). It's there because Hermes 0.13 doesn't do
    env-var interpolation in mcp_servers.headers; if and when it does,
    we move the token to an env var and stop persisting plaintext.
  - DB stores `agents.service_token_hash` — sha256 hex of the plaintext.
  - Verification is constant-time hex compare.

Token rotation: not implemented in v1. On any agent re-provision, the
token persists if `service_token_hash` is already set. To rotate, set
the hash column to NULL and the next cold-start mints a new one.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


def mint() -> tuple[str, str]:
    """Return (plaintext, sha256_hex). Plaintext is 43-char base64url
    (token_urlsafe(32) → 256 bits of entropy)."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_(plaintext)


def hash_(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def verify(plaintext: str, expected_hash: str) -> bool:
    """Constant-time compare. Both arguments expected as strings."""
    if not plaintext or not expected_hash:
        return False
    return hmac.compare_digest(hash_(plaintext), expected_hash)
