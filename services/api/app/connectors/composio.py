"""Composio-backed connector — covers the long tail.

Phase 2 implementation will hit Composio's REST + MCP endpoints. This is the
shape the gateway codes against; concrete HTTP wiring lands with the Gmail
flow.
"""
from typing import Any
from uuid import UUID

from .base import Connector, ConnectorLayer, OAuthLink, ToolCall, ToolResult


class ComposioConnector(Connector):
    layer = ConnectorLayer.COMPOSIO

    def __init__(self, provider: str):
        self.provider = provider

    async def begin_oauth(
        self, organization_id: UUID, redirect_uri: str
    ) -> OAuthLink:
        raise NotImplementedError("Phase 2: wire to Composio /v1/connectedAccounts")

    async def complete_oauth(
        self, organization_id: UUID, code: str, state: str
    ) -> dict[str, Any]:
        raise NotImplementedError("Phase 2")

    async def list_tools(self, organization_id: UUID) -> list[dict[str, Any]]:
        raise NotImplementedError("Phase 2: GET /v1/actions?appNames={provider}")

    async def call(self, tool_call: ToolCall) -> ToolResult:
        raise NotImplementedError("Phase 2: POST /v1/actions/{slug}/execute")
