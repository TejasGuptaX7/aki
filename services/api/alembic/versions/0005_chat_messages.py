"""chat_messages: persist user + assistant turns per agent

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17

Chat history now survives page refreshes, device switches, and container
hibernation. Each row is one turn (user message OR assistant message) tied
to an (org, agent) pair.

Append-only at the application layer (no UPDATE/DELETE triggers — we want
the audit-log invariants, but for chat we may want to support delete-thread
in v2 without a migration).

Tool calls + Hermes internal events stay in `audit_log` — this table only
holds what the user typed and what the assistant said back as visible text.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="cascade"),
                  nullable=False),
        # 'user' | 'assistant' | 'system' — keeping as varchar instead of
        # an enum so adding 'tool' / 'function' later is just a code change.
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # Composite index supporting the common query: "give me the last N rows
    # for this (org, agent) in chronological order". Descending id is the
    # default sort direction we paginate by.
    op.create_index(
        "ix_chat_messages_org_agent_id",
        "chat_messages",
        ["organization_id", "agent_id", "id"],
    )

    op.execute("alter table chat_messages enable row level security")
    op.execute("""
        create policy chat_messages_org_isolation on chat_messages
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)


def downgrade() -> None:
    op.execute("drop policy if exists chat_messages_org_isolation on chat_messages")
    op.execute("alter table chat_messages disable row level security")
    op.drop_index("ix_chat_messages_org_agent_id", table_name="chat_messages")
    op.drop_table("chat_messages")
