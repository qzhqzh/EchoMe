"""Project constraint graph and artifact models."""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.memory import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectArtifact(Base):
    """An immutable indexed revision of a project artifact."""

    __tablename__ = "project_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    logical_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="document")
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash_algorithm: Mapped[str] = mapped_column(String(16), nullable=False, default="sha256")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    artifact_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="current")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_artifacts.id"), nullable=True
    )
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('requirement','design','document','issue','code','test','pr','commit','memory')",
            name="valid_project_artifact_kind",
        ),
        CheckConstraint(
            "status IN ('current','stale','missing')", name="valid_project_artifact_status"
        ),
        UniqueConstraint(
            "user_id",
            "project_id",
            "logical_path",
            "content_hash",
            name="uq_project_artifact_revision",
        ),
        Index("idx_project_artifacts_project_status", "user_id", "project_id", "status"),
        Index("idx_project_artifacts_project_path", "user_id", "project_id", "logical_path"),
        Index(
            "uq_project_artifacts_current_path",
            "user_id",
            "project_id",
            "logical_path",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
    )


class ProjectConstraint(Base):
    """A canonical, version-aware project constraint."""

    __tablename__ = "project_constraints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="architecture")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    stability: Mapped[str] = mapped_column(String(16), nullable=False, default="evolving")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    embedding = mapped_column(Vector(1024), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=True
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('functional','nonfunctional','architecture','process','security','data','compatibility')",
            name="valid_project_constraint_kind",
        ),
        CheckConstraint(
            "status IN ('proposed','active','uncertain','superseded','deprecated')",
            name="valid_project_constraint_status",
        ),
        CheckConstraint(
            "stability IN ('invariant','evolving','temporary')",
            name="valid_project_constraint_stability",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_constraint_confidence"),
        Index("idx_project_constraints_project_status", "user_id", "project_id", "status"),
        Index("idx_project_constraints_project_kind", "user_id", "project_id", "kind"),
        Index("idx_project_constraints_previous_version", "previous_version_id"),
        UniqueConstraint("previous_version_id", name="uq_project_constraints_previous_version"),
        Index("idx_project_constraints_tags", "tags", postgresql_using="gin"),
        Index(
            "idx_project_constraints_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ConstraintEdge(Base):
    """A directed relationship between two project constraints."""

    __tablename__ = "constraint_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_constraint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=False
    )
    target_constraint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "relation IN ('depends_on','conflicts_with','refines','supersedes','impacts')",
            name="valid_constraint_edge_relation",
        ),
        UniqueConstraint(
            "user_id",
            "source_constraint_id",
            "target_constraint_id",
            "relation",
            name="uq_constraint_edge",
        ),
        Index("idx_constraint_edges_project", "user_id", "project_id"),
        Index("idx_constraint_edges_source", "source_constraint_id"),
        Index("idx_constraint_edges_target", "target_constraint_id"),
    )


class ConstraintEvidence(Base):
    """A typed link from a constraint to an artifact revision."""

    __tablename__ = "constraint_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    constraint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_artifacts.id"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "relation IN ('originates_from','implemented_by','verified_by','discussed_in','violated_by')",
            name="valid_constraint_evidence_relation",
        ),
        UniqueConstraint(
            "user_id",
            "constraint_id",
            "artifact_id",
            "relation",
            name="uq_constraint_evidence",
        ),
        Index("idx_constraint_evidence_project", "user_id", "project_id"),
        Index("idx_constraint_evidence_constraint", "constraint_id"),
        Index("idx_constraint_evidence_artifact", "artifact_id"),
    )


class ArtifactChunk(Base):
    """A rebuildable, independently retrievable slice of an artifact revision."""

    __tablename__ = "artifact_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_artifacts.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding = mapped_column(Vector(1024), nullable=True)
    search_vector = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    producer: Mapped[str] = mapped_column(String(64), nullable=False, default="echome")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("artifact_id", "ordinal", name="uq_artifact_chunk_ordinal"),
        Index("idx_artifact_chunks_project", "user_id", "project_id"),
        Index("idx_artifact_chunks_artifact", "artifact_id"),
        Index("idx_artifact_chunks_fts", "search_vector", postgresql_using="gin"),
        Index(
            "idx_artifact_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ContextRun(Base):
    """An append-only trace of one project context compilation."""

    __tablename__ = "context_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    changed_paths: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    token_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    selected: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint("mode IN ('local','overview','impact')", name="valid_context_run_mode"),
        CheckConstraint("status IN ('completed','failed')", name="valid_context_run_status"),
        Index("idx_context_runs_project_created", "user_id", "project_id", "created_at"),
    )


class KnowledgeView(Base):
    """A versioned derived project summary with a source freshness watermark."""

    __tablename__ = "knowledge_views"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="summary")
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_watermark: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    refresh_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="current")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    producer: Mapped[str] = mapped_column(String(64), nullable=False, default="client")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_views.id"), nullable=True
    )
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('summary','mental_model','community')", name="valid_knowledge_view_kind"
        ),
        CheckConstraint(
            "refresh_mode IN ('manual','derived')", name="valid_knowledge_view_refresh_mode"
        ),
        CheckConstraint(
            "status IN ('current','stale','superseded')", name="valid_knowledge_view_status"
        ),
        Index("idx_knowledge_views_project_status", "user_id", "project_id", "status"),
    )


class ConstraintRevalidationProposal(Base):
    """A validated proposal to revise a constraint after its evidence changes."""

    __tablename__ = "constraint_revalidation_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    constraint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=False
    )
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposal: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    applied_constraint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_constraints.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','applied','rejected','expired')",
            name="valid_constraint_revalidation_status",
        ),
        UniqueConstraint(
            "user_id",
            "project_id",
            "idempotency_key",
            name="uq_constraint_revalidation_idempotency",
        ),
        Index(
            "idx_constraint_revalidation_project_status",
            "user_id",
            "project_id",
            "status",
        ),
    )


class ProjectEvent(Base):
    """An append-only project episode such as a failure, fix, or test result."""

    __tablename__ = "project_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="client")
    source_ref: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('issue','attempt','failure','fix','decision','test_result','deploy','note')",
            name="valid_project_event_type",
        ),
        UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_project_event_idempotency"
        ),
        Index("idx_project_events_project_time", "user_id", "project_id", "occurred_at"),
        Index("idx_project_events_project_type", "user_id", "project_id", "event_type"),
    )


class EventLink(Base):
    """A typed relation from an event to project evidence or another event."""

    __tablename__ = "event_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_events.id"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    link_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('memory','constraint','artifact','event')",
            name="valid_event_link_target_type",
        ),
        UniqueConstraint(
            "user_id",
            "event_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_event_link",
        ),
        Index("idx_event_links_project", "user_id", "project_id"),
        Index("idx_event_links_event", "event_id"),
        Index("idx_event_links_target", "target_type", "target_id"),
    )


class ContextQualitySnapshot(Base):
    """An append-only fixed-dataset quality result used by automation gates."""

    __tablename__ = "context_quality_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    dataset_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    k: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('manual','background','ci')", name="valid_quality_snapshot_trigger"
        ),
        UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_quality_snapshot_idempotency"
        ),
        Index(
            "idx_quality_snapshots_project_created",
            "user_id",
            "project_id",
            "created_at",
        ),
    )


class AutomationProposalRun(Base):
    """An auditable dry-run or proposal-only automation invocation."""

    __tablename__ = "automation_proposal_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="dry_run")
    gate: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    plans: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    generated_proposal_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('dry_run','generated','gate_rejected')",
            name="valid_automation_proposal_run_status",
        ),
        UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_automation_run_idempotency"
        ),
        Index(
            "idx_automation_runs_project_created",
            "user_id",
            "project_id",
            "created_at",
        ),
    )
