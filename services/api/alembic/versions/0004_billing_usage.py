"""billing_usage: per-org, per-day usage rollups for Stripe metering

A nightly job sums `audit_log.payload.cost_usd` per org per day and writes
one `billing_usage` row. Idempotent on (organization_id, day) so retries
don't double-bill.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_usage",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="cascade"),
            nullable=False,
        ),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("chat_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("job_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("tool_call_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("stripe_event_id", sa.String(128)),
        sa.Column("stripe_pushed_at", sa.DateTime(timezone=True)),
        sa.Column("breakdown", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "day", name="uq_billing_usage_org_day"),
    )
    op.create_index("ix_billing_usage_day", "billing_usage", ["day"])

    op.execute("alter table billing_usage enable row level security")
    op.execute("""
        create policy billing_usage_org_isolation on billing_usage
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)


def downgrade() -> None:
    op.execute("drop policy if exists billing_usage_org_isolation on billing_usage")
    op.execute("alter table billing_usage disable row level security")
    op.drop_index("ix_billing_usage_day", table_name="billing_usage")
    op.drop_table("billing_usage")
