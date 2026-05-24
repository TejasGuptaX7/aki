"""initial schema: orgs, users (single-org), connections, memory, audit

Revision ID: 0001
Revises:
Create Date: 2026-05-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create extension if not exists pgcrypto")
    op.execute("create extension if not exists vector")

    op.create_table(
        "organizations",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "users",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("clerk_user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="restrict"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_org", "users", ["organization_id"])

    op.create_table(
        "connections",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("layer", sa.String(32), nullable=False),  # native|composio|custom
        sa.Column("external_account_id", sa.String(255)),
        sa.Column("scopes", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_connections_org_provider", "connections", ["organization_id", "provider"])

    op.create_table(
        "org_memory",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("version", sa.BigInteger, server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "key", name="uq_org_memory_key"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target", sa.String(255)),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("prev_hash", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_org_created", "audit_log", ["organization_id", "created_at"])

    # Block UPDATE/DELETE on audit_log at the database level.
    op.execute("""
        create or replace function audit_log_no_mutate() returns trigger
        language plpgsql as $$
        begin
            raise exception 'audit_log is append-only';
        end;
        $$;
    """)
    op.execute("""
        create trigger audit_log_no_update before update on audit_log
        for each row execute function audit_log_no_mutate();
    """)
    op.execute("""
        create trigger audit_log_no_delete before delete on audit_log
        for each row execute function audit_log_no_mutate();
    """)

    # ── Row-level security: one policy per tenant-scoped table ─────────────
    for table in ("users", "connections", "org_memory", "audit_log"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"""
            create policy {table}_org_isolation on {table}
            using (organization_id = current_setting('app.org_id', true)::uuid)
            with check (organization_id = current_setting('app.org_id', true)::uuid)
        """)


def downgrade() -> None:
    for table in ("audit_log", "org_memory", "connections", "users"):
        op.execute(f"drop policy if exists {table}_org_isolation on {table}")
        op.execute(f"alter table {table} disable row level security")

    op.execute("drop trigger if exists audit_log_no_delete on audit_log")
    op.execute("drop trigger if exists audit_log_no_update on audit_log")
    op.execute("drop function if exists audit_log_no_mutate")

    op.drop_index("ix_audit_org_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("org_memory")
    op.drop_index("ix_connections_org_provider", table_name="connections")
    op.drop_table("connections")
    op.drop_index("ix_users_org", table_name="users")
    op.drop_table("users")
    op.drop_table("organizations")
