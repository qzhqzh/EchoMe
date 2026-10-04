"""Atomic, source-backed knowledge for named recurring scenes."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.memory import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SceneKnowledge(Base):
    __tablename__ = "scene_knowledge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_scene_knowledge_user_slug"),
        CheckConstraint("status IN ('active','archived')", name="valid_scene_knowledge_status"),
        Index("idx_scene_knowledge_user_project", "user_id", "project_id"),
    )


class SceneKnowledgeEntry(Base):
    __tablename__ = "scene_knowledge_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scene_knowledge.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    origin_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    validations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint("scene_id", "category", "number", name="uq_scene_entry_number"),
        CheckConstraint(
            "category IN ('fact','observation','sop','caution','work')",
            name="valid_scene_entry_category",
        ),
        CheckConstraint(
            "status IN ('active','needs_review','archived')",
            name="valid_scene_entry_status",
        ),
        CheckConstraint("revision >= 1", name="valid_scene_entry_revision"),
        Index("idx_scene_entries_user_scene", "user_id", "scene_id", "category"),
    )


class SceneKnowledgeChange(Base):
    """A complete previous or new snapshot for every accepted write."""

    __tablename__ = "scene_knowledge_changes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scene_knowledge_entries.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("entry_id", "revision", name="uq_scene_change_revision"),
        CheckConstraint("action IN ('add','correct','status')", name="valid_scene_change_action"),
        Index("idx_scene_changes_user_entry", "user_id", "entry_id", "revision"),
    )
