"""Versioned reusable scenarios and resumable scenario items."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Scenario(Base):
    """Stable user-owned identity for a repeatable procedure."""

    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_scenarios_user_slug"),
        CheckConstraint("status IN ('draft','active','disabled')", name="valid_scenario_status"),
        Index("idx_scenarios_user_project_status", "user_id", "project_id", "status"),
    )


class ScenarioVersion(Base):
    """Immutable definition after publication; existing items keep this version."""

    __tablename__ = "scenario_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    validation_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_scenario_version"),
        Index("idx_scenario_versions_user_scenario", "user_id", "scenario_id"),
    )


class ScenarioItem(Base):
    """One invocation or continuous matter, optionally pinned to a published procedure."""

    __tablename__ = "scenario_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_versions.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    working_plan: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    phase: Mapped[str] = mapped_column(String(128), nullable=False, default="ready")
    parameters: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    environment: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_observation: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_summary: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_signal_key: Mapped[str | None] = mapped_column(String(256))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "(scenario_id IS NULL AND version_id IS NULL AND working_plan IS NOT NULL) "
            "OR (scenario_id IS NOT NULL AND version_id IS NOT NULL)",
            name="valid_scenario_item_binding",
        ),
        CheckConstraint("mode IN ('one_off','continuous')", name="valid_scenario_item_mode"),
        CheckConstraint(
            "status IN ('active','paused','completed')", name="valid_scenario_item_status"
        ),
        CheckConstraint(
            "current_observation IN ('unknown','normal','alert')",
            name="valid_scenario_observation",
        ),
        Index("idx_scenario_items_user_status_due", "user_id", "status", "next_check_at"),
        Index("idx_scenario_items_user_scenario", "user_id", "scenario_id"),
    )


class ScenarioRun(Base):
    """One claimed execution attempt with an idempotent completion."""

    __tablename__ = "scenario_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_items.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_versions.id"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    outcome: Mapped[str | None] = mapped_column(String(16))
    observation: Mapped[str | None] = mapped_column(String(16))
    summary: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    event_key: Mapped[str | None] = mapped_column(String(128))
    signal: Mapped[str | None] = mapped_column(String(32))
    notification_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("item_id", "idempotency_key", name="uq_scenario_run_idempotency"),
        CheckConstraint(
            "status IN ('running','completed','abandoned')", name="valid_scenario_run_status"
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('success','failure','skipped')",
            name="valid_scenario_run_outcome",
        ),
        CheckConstraint(
            "observation IS NULL OR observation IN ('unknown','normal','alert')",
            name="valid_scenario_run_observation",
        ),
        Index("idx_scenario_runs_user_item_started", "user_id", "item_id", "started_at"),
    )
