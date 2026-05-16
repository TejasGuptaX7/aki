"""Connector adapter for Hermes' first-party plugins.

Hermes already ships native integrations for Gmail, Calendar, GitHub, Linear,
Canva. We surface them through the same `Connector` interface so the gateway
and UI don't have to care which layer fulfils a tool call.
"""
from typing import Any
from uuid import UUID

from .base import Connector, ConnectorLayer, OAuthLink, ToolCall, ToolResult


SUPPORTED = {"gmail", "calendar", "github", "linear", "canva"}


class HermesNativeConnector(Connector):
    layer = ConnectorLayer.NATIVE

    def __init__(self, provider: str):
        if provider not in SUPPORTED:
            raise ValueError(f"no native Hermes plugin for {provider!r}")
        self.provider = provider

    async def begin_oauth(
        self, organization_id: UUID, redirect_uri: str
    ) -> OAuthLink:
        raise NotImplementedError(
            "Phase 4: delegate to Hermes' OAuth endpoint for this org's process"
        )

    async def complete_oauth(
        self, organization_id: UUID, code: str, state: str
    ) -> dict[str, Any]:
        raise NotImplementedError("Phase 4")

    async def list_tools(self, organization_id: UUID) -> list[dict[str, Any]]:
        raise NotImplementedError("Phase 4: read from MCP tools/list")

    async def call(self, tool_call: ToolCall) -> ToolResult:
        raise NotImplementedError("Phase 4: forward to per-org Hermes process")
