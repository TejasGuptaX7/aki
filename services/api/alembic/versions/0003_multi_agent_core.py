"""multi-agent core: agents, agent_memory, agent_id columns, rate_limits, approvals

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-16

Layers the multi-agent model on top of the org-scoped foundation.

  - agents:       many named long-lived agents per org (e.g. "Aki Sales")
  - agent_memory: replaces org_memory; each agent has its own namespace
  - connections.agent_id, audit_log.agent_id: nullable; NULL = org-wide
  - rate_limits:  per-org daily counters for the no-billing abuse defense
  - approvals:    tier-2 consent inbox (tool wants to run, user must say yes)

Data migration: every existing org gets one default agent named "Aki" so
existing chat sessions and org_memory rows survive. org_memory is then
dropped.

RLS continues to scope by organization_id only (the tenant boundary).
Cross-agent isolation inside an org is enforced by application code
(`WHERE agent_id = X` in queries, per-profile filesystem dirs). Bugs
at that layer leak between two of one company's own agents, which is
a UX bug, not a cross-tenant breach.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agents ──────────────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False, server_default=""),
        sa.Column("browser_profile_id", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("hibernated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "slug", name="uq_agents_org_slug"),
    )
    op.create_index("ix_agents_org", "agents", ["organization_id"])

    # ── agent_memory (replaces org_memory) ──────────────────────────────────
    op.create_table(
        "agent_memory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("version", sa.BigInteger, server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("agent_id", "key", name="uq_agent_memory_key"),
    )
    op.create_index("ix_agent_memory_org_agent",
                    "agent_memory", ["organization_id", "agent_id"])

    # ── connections.agent_id ────────────────────────────────────────────────
    # Nullable: NULL means org-wide (any agent in this org may use it).
    # Set means this connection belongs to a single agent.
    op.add_column("connections",
                  sa.Column("agent_id", UUID(as_uuid=True),
                            sa.ForeignKey("agents.id", ondelete="cascade")))
    op.create_index("ix_connections_org_agent_provider",
                    "connections", ["organization_id", "agent_id", "provider"])

    # ── audit_log.agent_id ──────────────────────────────────────────────────
    # Nullable: org-level events (provisioning, OAuth callbacks) carry NULL.
    # Agent actions (chat.start, chat.tool_call, chat.complete) carry agent_id.
    op.add_column("audit_log",
                  sa.Column("agent_id", UUID(as_uuid=True),
                            sa.ForeignKey("agents.id", ondelete="set null")))
    op.create_index("ix_audit_org_agent_created",
                    "audit_log", ["organization_id", "agent_id", "created_at"])

    # ── rate_limits (daily per-org counters) ────────────────────────────────
    # llm_cents stored as integer cents so daily increments stay atomic.
    op.create_table(
        "rate_limits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("actions_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("browser_seconds", sa.Integer, server_default="0", nullable=False),
        sa.Column("llm_cents", sa.Integer, server_default="0", nullable=False),
        sa.UniqueConstraint("organization_id", "period_start",
                            name="uq_rate_limits_org_day"),
    )

    # ── approvals (tier-2 consent inbox) ────────────────────────────────────
    # Default 10-minute TTL: if the user doesn't respond, the request expires
    # and the agent gets a "denied (timeout)" back so it doesn't hang forever.
    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("tool", sa.String(128), nullable=False),
        sa.Column("args", JSONB,
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("reason", sa.Text, server_default="", nullable=False),
        sa.Column("status", sa.String(32),
                  server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now() + interval '10 minutes'"),
                  nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("responded_by", sa.String(255)),
    )
    op.create_index("ix_approvals_org_status_created",
                    "approvals", ["organization_id", "status", "created_at"])

    # ── Data migration: default agent per org + org_memory → agent_memory ───
    # The system_prompt here is the v1 default brief. Per-agent system prompts
    # are user-editable from the UI; this row is just so existing orgs aren't
    # left without anything to chat with.
    # Dollar-quoted string ($$...$$) avoids the apostrophe-escape mess and
    # the Postgres "adjacent E-string concatenation" gotcha.
    op.execute("""
        insert into agents (organization_id, name, slug, system_prompt, status)
        select id, 'Aki', 'aki',
               $$You are Aki, the company's assistant. Be honest about what you did, cite sources, and ask before doing anything irreversible.$$,
               'active'
        from organizations
        on conflict (organization_id, slug) do nothing;
    """)

    op.execute("""
        insert into agent_memory
            (organization_id, agent_id, key, value, version, updated_at)
        select om.organization_id,
               a.id,
               om.key,
               om.value,
               om.version,
               om.updated_at
        from org_memory om
        join agents a on a.organization_id = om.organization_id
                    and a.slug = 'aki';
    """)

    # ── Drop org_memory after backfill ──────────────────────────────────────
    op.execute("drop policy if exists org_memory_org_isolation on org_memory")
    op.execute("alter table org_memory disable row level security")
    op.drop_table("org_memory")

    # ── RLS on new tables ───────────────────────────────────────────────────
    # All scoped by organization_id (the tenant boundary). Cross-agent
    # filtering happens in application queries, not RLS.
    for table in ("agents", "agent_memory", "rate_limits", "approvals"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"""
            create policy {table}_org_isolation on {table}
            using (organization_id = current_setting('app.org_id', true)::uuid)
            with check (organization_id = current_setting('app.org_id', true)::uuid)
        """)


def downgrade() -> None:
    for table in ("approvals", "rate_limits", "agent_memory", "agents"):
        op.execute(f"drop policy if exists {table}_org_isolation on {table}")
        op.execute(f"alter table {table} disable row level security")

    op.create_table(
        "org_memory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("version", sa.BigInteger, server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("organization_id", "key", name="uq_org_memory_key"),
    )
    op.execute("alter table org_memory enable row level security")
    op.execute("""
        create policy org_memory_org_isolation on org_memory
        using (organization_id = current_setting('app.org_id', true)::uuid)
        with check (organization_id = current_setting('app.org_id', true)::uuid)
    """)
    # Collapse per-agent memory back to a single org row per key
    # (keep the most recently updated). Lossy by definition.
    op.execute("""
        insert into org_memory (organization_id, key, value, version, updated_at)
        select distinct on (organization_id, key)
               organization_id, key, value, version, updated_at
        from agent_memory
        order by organization_id, key, updated_at desc
    """)

    op.drop_index("ix_approvals_org_status_created", table_name="approvals")
    op.drop_table("approvals")
    op.drop_table("rate_limits")
    op.drop_index("ix_audit_org_agent_created", table_name="audit_log")
    op.drop_column("audit_log", "agent_id")
    op.drop_index("ix_connections_org_agent_provider", table_name="connections")
    op.drop_column("connections", "agent_id")
    op.drop_index("ix_agent_memory_org_agent", table_name="agent_memory")
    op.drop_table("agent_memory")
    op.drop_index("ix_agents_org", table_name="agents")
    op.drop_table("agents")
