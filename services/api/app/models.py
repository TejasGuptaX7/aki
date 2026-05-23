"""SQLAlchemy ORM models matching the latest Alembic head."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="restrict"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="cascade"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64))
    hermes_model_name: Mapped[str | None] = mapped_column(String(128))
    hermes_idle_minutes: Mapped[int] = mapped_column(Integer, default=15)
    notification_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Membership(Base):
    __tablename__ = "memberships"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="cascade"),
        primary_key=True,
    )
    department_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="cascade"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="cascade"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64))     # gmail | notion | …
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OrgMemory(Base):
    __tablename__ = "org_memory"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="cascade"),
        index=True,
    )
    department_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="cascade"),
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(255))
    brief: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    schedule_cron: Mapped[str | None] = mapped_column(String(128))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    brain_source_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("brain_sources.id", ondelete="set null"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="cascade"),
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class BrainSource(Base):
    __tablename__ = "brain_sources"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="cascade")
    )
    scope: Mapped[str] = mapped_column(String(16))        # org|department|user
    scope_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(32))
    uri: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str | None] = mapped_column(String(512))
    acl_principals: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BrainChunk(Base):
    __tablename__ = "brain_chunks"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("brain_sources.id", ondelete="cascade"),
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="cascade")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    # ts_vector is a generated column; we don't read it through ORM, only via raw SQL.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BrainFact(Base):
    __tablename__ = "brain_facts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="cascade")
    )
    scope: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1.0"))
    source_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("brain_sources.id", ondelete="set null")
    )
    superseded_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BillingUsage(Base):
    __tablename__ = "billing_usage"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="cascade"),
    )
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    chat_count: Mapped[int] = mapped_column(Integer, default=0)
    job_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    stripe_event_id: Mapped[str | None] = mapped_column(String(128))
    stripe_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AkiDevice(Base):
    __tablename__ = "aki_devices"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="cascade"),
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="cascade")
    )
    name: Mapped[str] = mapped_column(String(255))
    pubkey: Mapped[str] = mapped_column(Text)
    device_jwt_jti: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
