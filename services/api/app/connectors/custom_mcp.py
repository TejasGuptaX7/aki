"""Bring-your-own MCP / OpenAPI connector for internal company tools.

An org registers a connector by URL + auth header. The gateway speaks MCP
(`tools/list`, `tools/call`) or, for OpenAPI specs, generates tool stubs at
registration time.
"""
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .base import Connector, ConnectorLayer, OAuthLink, ToolCall, ToolResult


@dataclass
class CustomMCPSpec:
    url: str
    auth_header: str | None = None   # e.g. "Authorization: Bearer …"
    kind: str = "mcp"                # "mcp" | "openapi"


class CustomMCPConnector(Connector):
    layer = ConnectorLayer.CUSTOM

    def __init__(self, provider: str, spec: CustomMCPSpec):
        self.provider = provider
        self.spec = spec

    async def begin_oauth(
        self, organization_id: UUID, redirect_uri: str
    ) -> OAuthLink:
        # BYO MCP servers typically use a static auth header, not OAuth.
        raise NotImplementedError("custom connectors authenticate via stored header")

    async def complete_oauth(
        self, organization_id: UUID, code: str, state: str
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def list_tools(self, organization_id: UUID) -> list[dict[str, Any]]:
        raise NotImplementedError("Phase 4: speak MCP tools/list")

    async def call(self, tool_call: ToolCall) -> ToolResult:
        raise NotImplementedError("Phase 4: speak MCP tools/call")
