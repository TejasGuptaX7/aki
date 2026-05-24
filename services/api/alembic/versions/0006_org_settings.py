"""organizations.settings jsonb + stripe_customer_id, org_memory unique index

Adds org-level free-form settings (jsonb) and a Stripe customer id column for
billing. Also backfills a unique index on org_memory(organization_id, key).

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "settings",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
    )
    op.execute(
        "create index if not exists ix_org_settings on organizations using gin (settings)"
    )

    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.Text, nullable=True),
    )

    op.execute(
        "create unique index if not exists ix_org_memory_org_key on org_memory (organization_id, key)"
    )


def downgrade() -> None:
    op.execute("drop index if exists ix_org_memory_org_key")
    op.drop_column("organizations", "stripe_customer_id")
    op.execute("drop index if exists ix_org_settings")
    op.drop_column("organizations", "settings")
