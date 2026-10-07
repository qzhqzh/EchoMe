"""Versioned knowledge objects and same-owner, version-pinned references.

Payloads have kind-specific Pydantic contracts. The registry is the common identity
and revision mechanism; projects/questions never own entities or relations.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.memory import Base, _utcnow


class KnowledgeRecord(Base):
    __tablename__ = "knowledge_records"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_knowledge_record_owner"),
        UniqueConstraint("id", "user_id", "kind", name="uq_knowledge_record_kind"),
        CheckConstraint("revision > 0", name="ck_knowledge_record_revision"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND status = payload->>'status'",
            name="ck_knowledge_payload_status",
        ),
        CheckConstraint(
            "kind = 'project' OR project_id IS NULL", name="ck_knowledge_project_identity"
        ),
        CheckConstraint(
            "kind <> 'relation' OR ((payload->>'object_entity_id' IS NOT NULL) <> (payload->>'object_value' IS NOT NULL))",
            name="ck_knowledge_relation_object",
        ),
        CheckConstraint(
            "kind IN ('project','question','entity','relation','predicate','page',"
            "'source','placement','usage','deliverable','review','acceptance')",
            name="ck_knowledge_record_kind",
        ),
        Index("ix_knowledge_records_user_kind", "user_id", "kind", "status", "updated_at"),
        Index("ix_knowledge_records_payload", "payload", postgresql_using="gin"),
        Index("uq_knowledge_review_fingerprint", "user_id", "fingerprint", unique=True),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("projects.id", ondelete="RESTRICT"), unique=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="active")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "user_id"],
            ["knowledge_records.id", "knowledge_records.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("record_id", "revision", name="uq_knowledge_version_number"),
        UniqueConstraint("record_id", "user_id", "revision", name="uq_knowledge_version_owner"),
        CheckConstraint("revision > 0", name="ck_knowledge_version_revision"),
        Index("ix_knowledge_versions_user_record", "user_id", "record_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeReference(Base):
    """Immutable reference of a particular version, including target ownership/kind."""

    __tablename__ = "knowledge_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "user_id", "owner_revision"],
            [
                "knowledge_versions.record_id",
                "knowledge_versions.user_id",
                "knowledge_versions.revision",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_id", "user_id", "target_kind"],
            ["knowledge_records.id", "knowledge_records.user_id", "knowledge_records.kind"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_id", "user_id", "target_revision"],
            [
                "knowledge_versions.record_id",
                "knowledge_versions.user_id",
                "knowledge_versions.revision",
            ],
            ondelete="RESTRICT",
        ),
        Index("ix_knowledge_refs_owner", "user_id", "owner_id", "owner_revision"),
        Index("ix_knowledge_refs_target", "user_id", "target_id", "target_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    owner_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[str] = mapped_column(String(96), nullable=False)


class KnowledgeOverview(Base):
    """Current overview binding: one page per object and one object per page."""

    __tablename__ = "knowledge_overviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["page_id", "user_id"], ["knowledge_records.id", "knowledge_records.user_id"]
        ),
        ForeignKeyConstraint(
            ["target_id", "user_id"], ["knowledge_records.id", "knowledge_records.user_id"]
        ),
        UniqueConstraint("target_id", name="uq_knowledge_overview_target"),
        Index("ix_knowledge_overviews_user_target", "user_id", "target_id"),
    )
    page_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class KnowledgeDecision(Base):
    __tablename__ = "knowledge_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "user_id", "review_revision"],
            [
                "knowledge_versions.record_id",
                "knowledge_versions.user_id",
                "knowledge_versions.revision",
            ],
        ),
        Index("ix_knowledge_decisions_user_review", "user_id", "review_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeAgentToken(Base):
    __tablename__ = "knowledge_agent_tokens"
    __table_args__ = (Index("ix_knowledge_tokens_user", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"
    __table_args__ = (Index("ix_knowledge_assets_user", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
