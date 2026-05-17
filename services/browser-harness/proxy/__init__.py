"""v2 proxy layer for the Aki browser harness.

Routes per-(org, agent, platform) MCP tool calls to Steel.dev (free
tier) or Browserbase (production), so we don't run our own Chromium
pool. The wire contract is the v1 MCP surface plus a few v2-only
tools; see ../PROTOCOL_v2.md.
"""

__version__ = "2.0.0"
