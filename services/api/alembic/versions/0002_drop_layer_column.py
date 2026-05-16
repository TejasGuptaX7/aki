"""drop connections.layer

The three-layer connector abstraction (native|composio|custom) was speculative.
Provider + config jsonb carries everything we actually need; the source of a
connection (composio vs custom MCP) lives in config.source.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("connections", "layer")


def downgrade() -> None:
    op.add_column(
        "connections",
        sa.Column(
            "layer",
            sa.String(32),
            nullable=False,
            server_default="composio",
        ),
    )
