"""Connector abstraction.

Three layers feed the same UI surface; each one implements `Connector`.
Adding a new provider means registering one of:

  - HermesNativeConnector   — Hermes' first-party plugin (fastest, deepest)
  - ComposioConnector       — long-tail via Composio MCP
  - CustomMCPConnector      — BYO MCP URL or OpenAPI spec for internal tools
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID


class ConnectorLayer(str, Enum):
    NATIVE = "native"
    COMPOSIO = "composio"
    CUSTOM = "custom"


@dataclass(frozen=True)
class OAuthLink:
    """Returned by `begin_oauth`; the web app redirects the user here."""

    url: str
    state: str


@dataclass(frozen=True)
class ToolCall:
    name: str                         # e.g. "gmail.send_message"
    arguments: dict[str, Any]
    organization_id: UUID
    actor: str                        # user id or "agent:<run_id>"


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class Connector(ABC):
    """Single provider on a single org."""

    provider: str          # "gmail", "notion", …
    layer: ConnectorLayer

    @abstractmethod
    async def begin_oauth(
        self, organization_id: UUID, redirect_uri: str
    ) -> OAuthLink: ...

    @abstractmethod
    async def complete_oauth(
        self, organization_id: UUID, code: str, state: str
    ) -> dict[str, Any]:
        """Returns connection metadata to persist (scopes, external_account_id…)."""

    @abstractmethod
    async def list_tools(self, organization_id: UUID) -> list[dict[str, Any]]:
        """Tool schemas in MCP/OpenAI tool-spec shape, for the agent gateway."""

    @abstractmethod
    async def call(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call. The gateway has already done auth/permission/audit."""
