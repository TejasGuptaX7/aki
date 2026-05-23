"""departments + memberships + jobs + brain_* + aki_devices

Adds the multi-product schema:
  - departments / memberships — per-department membership replaces single-org
    membership at the API surface, but `users.organization_id` is preserved.
  - connections re-scoped to a department (backfilled to a "Default" dept
    per organization).
  - jobs / job_events — Phase 2 will dispatch these via the arq worker.
  - brain_sources / brain_chunks / brain_facts — embedding-indexed memory
    written by both Hermes and the future Aki desktop. ACL-aware.
  - aki_devices — paired laptops for the future Aki desktop. Ed25519 pubkey
    on file; API mints a device JWT per pair.

Every new tenant-scoped table gets the same RLS pattern as 0001_initial.py.
job_events is append-only via trigger (mirrors audit_log).

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── departments ─────────────────────────────────────────────────────────
    op.create_table(
        "departments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("hermes_model_name", sa.String(128)),
        sa.Column("hermes_idle_minutes", sa.Integer, server_default="15",
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_dept_org_slug"),
    )
    op.create_index("ix_departments_org", "departments", ["organization_id"])

    # ── memberships ─────────────────────────────────────────────────────────
    # Composite PK on (user_id, department_id). Role: owner|member|viewer.
    op.create_table(
        "memberships",
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="cascade"), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("role", sa.String(32), server_default="member", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "department_id", name="pk_memberships"),
    )
    op.create_index("ix_memberships_dept", "memberships", ["department_id"])

    # Memberships scope through department → organization. Use a SELECT EXISTS
    # for the policy; cheap enough since (department_id) is indexed.
    op.execute("alter table memberships enable row level security")
    op.execute("""
        create policy memberships_org_isolation on memberships
        using (exists (
            select 1 from departments d
            where d.id = memberships.department_id
              and d.organization_id = current_setting('app.org_id', true)::uuid
        ))
        with check (exists (
            select 1 from departments d
            where d.id = memberships.department_id
              and d.organization_id = current_setting('app.org_id', true)::uuid
        ))
    """)

    # ── connections: scope to a department ──────────────────────────────────
    # Backfill a Default department per org first, then point existing
    # connections at it, then enforce NOT NULL.
    op.execute("""
        insert into departments (organization_id, name, slug, created_at)
        select id, 'Default', 'default', now() from organizations
        on conflict do nothing
    """)

    op.add_column(
        "connections",
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id", ondelete="cascade")),
    )
    op.execute("""
        update connections c
        set department_id = (
            select id from departments d
            where d.organization_id = c.organization_id
              and d.slug = 'default'
            limit 1
        )
        where c.department_id is null
    """)
    op.alter_column("connections", "department_id", nullable=False)
    # The old index (org_id, provider) is superseded by the dept-scoped one.
    op.drop_index("ix_connections_org_provider", table_name="connections")
    op.create_index("ix_connections_dept_provider", "connections",
                    ["department_id", "provider"])

    # ── department-level RLS for departments table ──────────────────────────
    op.execute("alter table departments enable row level security")
    op.execute("""
        create policy departments_org_isolation on departments
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)

    # ── jobs ────────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("brief", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("schedule_cron", sa.String(128)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("result_summary", sa.Text),
        sa.Column("cost_usd", sa.Numeric(10, 4), server_default="0", nullable=False),
        sa.Column("brain_source_id", UUID(as_uuid=True)),  # FK added after brain_sources
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_jobs_status_next", "jobs", ["status", "next_run_at"])
    op.create_index("ix_jobs_dept_created", "jobs",
                    ["department_id", sa.text("created_at desc")])

    op.execute("alter table jobs enable row level security")
    op.execute("""
        create policy jobs_org_isolation on jobs
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)

    # ── job_events (append-only) ────────────────────────────────────────────
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job_id", UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="cascade"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_job_events_job_ts", "job_events", ["job_id", "ts"])

    op.execute("alter table job_events enable row level security")
    op.execute("""
        create policy job_events_org_isolation on job_events
        using (exists (
            select 1 from jobs j
            where j.id = job_events.job_id
              and j.organization_id = current_setting('app.org_id', true)::uuid
        ))
        with check (exists (
            select 1 from jobs j
            where j.id = job_events.job_id
              and j.organization_id = current_setting('app.org_id', true)::uuid
        ))
    """)

    op.execute("""
        create or replace function job_events_no_mutate() returns trigger
        language plpgsql as $$
        begin
            raise exception 'job_events is append-only';
        end;
        $$;
    """)
    op.execute("""
        create trigger job_events_no_update before update on job_events
        for each row execute function job_events_no_mutate();
    """)
    op.execute("""
        create trigger job_events_no_delete before delete on job_events
        for each row execute function job_events_no_mutate();
    """)

    # ── brain_sources ───────────────────────────────────────────────────────
    op.create_table(
        "brain_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),  # org|department|user
        sa.Column("scope_id", UUID(as_uuid=True)),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("uri", sa.String(1024)),
        sa.Column("title", sa.String(512)),
        sa.Column("acl_principals", JSONB,
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_brain_sources_org_created", "brain_sources",
                    ["organization_id", sa.text("created_at desc")])
    op.create_index("ix_brain_sources_scope", "brain_sources",
                    ["organization_id", "scope", "scope_id"])
    # Idempotency on (origin, uri) when uri is provided.
    op.create_index("ix_brain_sources_origin_uri", "brain_sources",
                    ["origin", "uri"], unique=True,
                    postgresql_where=sa.text("uri is not null"))

    op.execute("alter table brain_sources enable row level security")
    op.execute("""
        create policy brain_sources_org_isolation on brain_sources
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)

    # Now add the deferred FK from jobs.brain_source_id → brain_sources.id.
    op.create_foreign_key(
        "fk_jobs_brain_source", "jobs", "brain_sources",
        ["brain_source_id"], ["id"], ondelete="set null",
    )

    # ── brain_chunks ────────────────────────────────────────────────────────
    op.create_table(
        "brain_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", UUID(as_uuid=True),
                  sa.ForeignKey("brain_sources.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        # pgvector dim is fixed at table creation — text-embedding-3-small is 1536.
        # An upgrade to Voyage-3 (1024) needs a separate re-embed migration.
        sa.Column("embedding", Vector(1536)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # ts_vector is a generated column; can't be declared via Column() in a
    # portable way, so add it with raw SQL after table creation.
    op.execute("""
        alter table brain_chunks
        add column ts_vector tsvector
        generated always as (to_tsvector('english', content)) stored
    """)

    op.create_index("ix_brain_chunks_source", "brain_chunks", ["source_id"])
    op.execute("""
        create index ix_brain_chunks_embedding_hnsw on brain_chunks
        using hnsw (embedding vector_cosine_ops)
    """)
    op.execute("""
        create index ix_brain_chunks_tsv on brain_chunks
        using gin (ts_vector)
    """)

    op.execute("alter table brain_chunks enable row level security")
    op.execute("""
        create policy brain_chunks_org_isolation on brain_chunks
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)

    # ── brain_facts ─────────────────────────────────────────────────────────
    op.create_table(
        "brain_facts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_id", UUID(as_uuid=True)),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), server_default="1.0",
                  nullable=False),
        sa.Column("source_id", UUID(as_uuid=True),
                  sa.ForeignKey("brain_sources.id", ondelete="set null")),
        sa.Column("superseded_by", UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # Active (un-superseded) facts are unique per (org, scope, scope_id, key).
    op.execute("""
        create unique index uq_brain_facts_active
        on brain_facts (organization_id, scope, scope_id, key)
        where superseded_by is null
    """)

    op.execute("alter table brain_facts enable row level security")
    op.execute("""
        create policy brain_facts_org_isolation on brain_facts
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)

    # ── aki_devices ─────────────────────────────────────────────────────────
    op.create_table(
        "aki_devices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="cascade"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("pubkey", sa.Text, nullable=False),
        sa.Column("device_jwt_jti", sa.String(64)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_aki_devices_user", "aki_devices", ["user_id"])

    op.execute("alter table aki_devices enable row level security")
    op.execute("""
        create policy aki_devices_org_isolation on aki_devices
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)


def downgrade() -> None:
    for table in (
        "aki_devices", "brain_facts", "brain_chunks", "brain_sources",
        "job_events", "jobs", "memberships", "departments",
    ):
        op.execute(f"drop policy if exists {table}_org_isolation on {table}")
        op.execute(f"alter table {table} disable row level security")

    op.execute("drop trigger if exists job_events_no_delete on job_events")
    op.execute("drop trigger if exists job_events_no_update on job_events")
    op.execute("drop function if exists job_events_no_mutate")

    op.drop_constraint("fk_jobs_brain_source", "jobs", type_="foreignkey")

    op.drop_table("aki_devices")
    op.drop_table("brain_facts")
    op.drop_table("brain_chunks")
    op.drop_table("brain_sources")
    op.drop_table("job_events")
    op.drop_table("jobs")
    op.drop_table("memberships")

    # Revert connections.department_id and restore the old index.
    op.drop_index("ix_connections_dept_provider", table_name="connections")
    op.create_index("ix_connections_org_provider",
                    "connections", ["organization_id", "provider"])
    op.drop_column("connections", "department_id")

    op.drop_index("ix_departments_org", table_name="departments")
    op.drop_table("departments")
