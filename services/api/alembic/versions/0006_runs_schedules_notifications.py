"""agent_runs + agent_schedules + notifications

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-17

Three new tables for the long-running-agent + scheduling + ambient-notification
primitives:

  agent_runs:        one row per agent invocation lifecycle. Distinct from
                     audit_log (which is per-event); a run aggregates the
                     prompt + plan + final status + error. Used by the UI
                     to show "Aki Sales is working on X — step 3 of 5".

  agent_schedules:   cron-style triggers that fire a new agent_run with a
                     given prompt. Loaded by app/scheduler.py on startup.

  notifications:     ambient inbox the agent writes to when something needs
                     the human's attention asynchronously (a long task
                     finished, the agent has a question, the agent hit a
                     wall). The frontend polls; later this fans out to
                     Slack + email.

RLS scoped by organization_id (consistent with every other table). Cross-
agent isolation inside an org is application-layer (WHERE agent_id = X).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agent_runs ──────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="cascade"),
                  nullable=False),
        # status lifecycle: running → done | errored | canceled
        sa.Column("status", sa.String(32),
                  server_default="running", nullable=False),
        # plan is a list of {text, status, started_at, completed_at} objects.
        # `status` per step: pending | in_progress | done | skipped. The agent
        # updates this via the update_plan() MCP tool; the UI renders the list.
        sa.Column("plan", JSONB,
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("current_index", sa.Integer,
                  server_default="0", nullable=False),
        sa.Column("prompt", sa.Text, server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
    )
    # The hot query: "show me the current (non-completed) run for this org +
    # agent" and "list orgs that have a running run" (for hibernation skip).
    op.create_index(
        "ix_agent_runs_org_status",
        "agent_runs",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_agent_runs_org_agent_started",
        "agent_runs",
        ["organization_id", "agent_id", "started_at"],
    )

    # ── agent_schedules ─────────────────────────────────────────────────────
    op.create_table(
        "agent_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="cascade"),
                  nullable=False),
        # Standard 5-field cron expression in UTC. APScheduler parses it.
        sa.Column("cron", sa.String(128), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean,
                  server_default=sa.text("true"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_agent_schedules_org_agent",
        "agent_schedules",
        ["organization_id", "agent_id"],
    )
    op.create_index(
        "ix_agent_schedules_enabled",
        "agent_schedules",
        ["enabled"],
    )

    # ── notifications ───────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="cascade"),
                  nullable=False),
        # Nullable: a system-level notification (e.g. billing/usage alert)
        # carries no agent_id. Most notifications will have one.
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="set null")),
        # kind: question | done | error  — extensible; varchar not enum.
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, server_default="", nullable=False),
        sa.Column("payload", JSONB,
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # "give me the user's undismissed notifications" — the FE poll path.
    op.create_index(
        "ix_notifications_org_dismissed",
        "notifications",
        ["organization_id", "dismissed_at"],
    )

    # ── RLS ─────────────────────────────────────────────────────────────────
    for table in ("agent_runs", "agent_schedules", "notifications"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"""
            create policy {table}_org_isolation on {table}
            using (organization_id = current_setting('app.org_id', true)::uuid)
            with check (organization_id = current_setting('app.org_id', true)::uuid)
        """)


def downgrade() -> None:
    for table in ("notifications", "agent_schedules", "agent_runs"):
        op.execute(f"drop policy if exists {table}_org_isolation on {table}")
        op.execute(f"alter table {table} disable row level security")
    op.drop_index("ix_notifications_org_dismissed", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_agent_schedules_enabled", table_name="agent_schedules")
    op.drop_index("ix_agent_schedules_org_agent", table_name="agent_schedules")
    op.drop_table("agent_schedules")
    op.drop_index("ix_agent_runs_org_agent_started", table_name="agent_runs")
    op.drop_index("ix_agent_runs_org_status", table_name="agent_runs")
    op.drop_table("agent_runs")
