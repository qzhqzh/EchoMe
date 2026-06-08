"""SQLAlchemy models for memories and projects."""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Memory(Base):
    """A single memory entry in the vault."""

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    # Content
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Three axes
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    layer: Mapped[str] = mapped_column(String(4), nullable=False)
    scope_global: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scope_projects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scope_exclude: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Metadata
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_core: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sleep_state: Mapped[str] = mapped_column(String(16), nullable=False, default="fresh")
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id"), nullable=True
    )
    derived_from: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Multi-user fields
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private"
    )  # private / public
    forked_from: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Embedding vector (dimension must match DB column and embedding service output)
    # bge-m3 outputs 1024 dimensions
    embedding = mapped_column(Vector(1024), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('identity','method','stack','guardrail','template',"
            "'decision','context','style','project','reasoning')",
            name="valid_type",
        ),
        CheckConstraint("layer IN ('L0','L1','L2')", name="valid_layer"),
        CheckConstraint(
            "status IN ('active','ai_review','pending','deprecated','archived')", name="valid_status"
        ),
        CheckConstraint(
            "sleep_state IN ('fresh','reviewed','distilled','superseded')",
            name="valid_sleep_state",
        ),
        CheckConstraint("priority BETWEEN 1 AND 10", name="valid_priority"),
        Index("idx_memories_user_type", "user_id", "type"),
        Index("idx_memories_user_layer", "user_id", "layer"),
        Index("idx_memories_user_status", "user_id", "status"),
        Index("idx_memories_user_sleep_state", "user_id", "sleep_state"),
        Index("idx_memories_tags", "tags", postgresql_using="gin"),
        Index("idx_memories_scope_projects", "scope_projects", postgresql_using="gin"),
    )


class Project(Base):
    """A project that memories can be scoped to."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_remote: Mapped[str | None] = mapped_column(String(512), nullable=True)
    path_patterns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class SyncLog(Base):
    """Log of sync operations."""

    __tablename__ = "sync_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    memories_affected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    client_info: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class SleepSession(Base):
    """A memory sleep planning and apply session."""

    __tablename__ = "sleep_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="client_generated")
    candidate_memory_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    text_proposal: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_proposal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','proposed','approved','applied','rejected')",
            name="valid_sleep_session_status",
        ),
        CheckConstraint(
            "mode IN ('server_generated','client_generated')",
            name="valid_sleep_session_mode",
        ),
        Index("idx_sleep_sessions_user_status", "user_id", "status"),
        Index("idx_sleep_sessions_user_project", "user_id", "project_id"),
    )


class MemoryEdge(Base):
    """Relationship between two memories."""

    __tablename__ = "memory_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id"), nullable=False
    )
    target_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sleep_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sleep_sessions.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="sleep")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "relation IN ('derived_from','supersedes','superseded_by','duplicates',"
            "'conflicts_with','specializes','related_to')",
            name="valid_memory_edge_relation",
        ),
        Index("idx_memory_edges_user_source", "user_id", "source_memory_id"),
        Index("idx_memory_edges_user_target", "user_id", "target_memory_id"),
        Index("idx_memory_edges_sleep_session", "sleep_session_id"),
    )
