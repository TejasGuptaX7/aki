"""departments.notification_config jsonb

Per-dept delivery config: slack channel, future webhook URLs, per-dept
muting. Putting it in jsonb so adding a new delivery method later is
not a schema change.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column(
            "notification_config",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("departments", "notification_config")
