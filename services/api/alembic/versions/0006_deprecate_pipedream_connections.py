"""mark legacy pipedream/composio connection rows as deprecated

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-17

Phase 3g pivot: dropped the Pipedream Connect integration in favor of
native OAuth (top-5 providers: gmail/slack/notion/linear/hubspot) plus
Arcade.dev for the long tail. Existing rows whose config.source is
"pipedream" or the older "composio" are stale — their MCP tools no
longer materialize.

This migration sets `status = 'deprecated'` on those rows so the UI
can surface a "reconnect via /connect" banner instead of leaving the
user staring at a connection that silently produces no tools.

Idempotent: re-running on a database that's already been migrated
updates zero rows. Reversible: downgrade flips status back to 'active'
for the same set — useful only if we ever decide to re-introduce
Pipedream (we won't).
"""
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE connections
        SET status = 'deprecated'
        WHERE status = 'active'
          AND config ->> 'source' IN ('pipedream', 'composio')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE connections
        SET status = 'active'
        WHERE status = 'deprecated'
          AND config ->> 'source' IN ('pipedream', 'composio')
        """
    )
