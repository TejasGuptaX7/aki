"""agents.service_token_hash for the request_approval internal-MCP auth path

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17

Each agent gets a service token used by its Hermes profile to call back to
our control plane's internal MCP server (the one that hosts request_approval
and any future agent-only tools). We store sha256(token) here; the plaintext
lives only inside the per-agent workspace's `config.yaml` mcp_servers headers
on the host volume (mode 0600), and is minted on first cold-start.

Nullable so existing agents (the default "aki" + any others created before
this migration) can be migrated lazily — `_seed_agent_workspace` mints +
back-fills on next boot.
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("service_token_hash", sa.String(128), nullable=True),
    )
    # Index supports the auth-path lookup by token hash (agent_internal MCP
    # finds the agent by hash + verifies the org/agent ids match).
    op.create_index(
        "ix_agents_service_token_hash",
        "agents",
        ["service_token_hash"],
        unique=True,
        postgresql_where=sa.text("service_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agents_service_token_hash", table_name="agents")
    op.drop_column("agents", "service_token_hash")
