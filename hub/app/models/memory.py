"""SQLAlchemy models for memories and projects."""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, SmallInteger, String, Text
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

    # Multi-user fields
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private"
    )  # private / public
    forked_from: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Embedding vector (dimension must match DB column and embedding service output)
    # If mismatch occurs, update DB: ALTER TABLE memories ALTER COLUMN embedding TYPE vector(N);
    # Or update config: ECHOME_EMBEDDING_DIMENSIONS=N
    embedding = mapped_column(Vector(1536), nullable=True)

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
            "status IN ('active','pending','deprecated','archived')", name="valid_status"
        ),
        CheckConstraint("priority BETWEEN 1 AND 10", name="valid_priority"),
        Index("idx_memories_user_type", "user_id", "type"),
        Index("idx_memories_user_layer", "user_id", "layer"),
        Index("idx_memories_user_status", "user_id", "status"),
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
