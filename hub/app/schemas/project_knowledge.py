"""Schemas for project artifacts, constraints, and impact analysis."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ArtifactKind = Literal[
    "requirement", "design", "document", "issue", "code", "test", "pr", "commit", "memory"
]
ConstraintKind = Literal[
    "functional", "nonfunctional", "architecture", "process", "security", "data", "compatibility"
]
ConstraintStatus = Literal["proposed", "active", "uncertain", "superseded", "deprecated"]
ConstraintStability = Literal["invariant", "evolving", "temporary"]


class ArtifactManifestItem(BaseModel):
    logical_path: str = Field(..., min_length=1, max_length=1024)
    content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(..., ge=0)
    kind: ArtifactKind = "document"
    title: str = Field(..., min_length=1, max_length=256)
    source_uri: str | None = Field(None, max_length=2048)
    metadata: dict = Field(default_factory=dict)


class ArtifactSyncCheckRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    artifacts: list[ArtifactManifestItem] = Field(..., max_length=5000)


class ArtifactUploadItem(ArtifactManifestItem):
    content: str = Field(..., max_length=2_000_000)


class ArtifactSyncApplyRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    artifacts: list[ArtifactUploadItem] = Field(..., min_length=1, max_length=200)


class ConstraintCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=256)
    statement: str = Field(..., min_length=1, max_length=100_000)
    rationale: str | None = Field(None, max_length=100_000)
    kind: ConstraintKind = "architecture"
    status: ConstraintStatus = "proposed"
    stability: ConstraintStability = "evolving"
    confidence: float = Field(0.7, ge=0, le=1)
    source: Literal["manual", "ai", "imported", "bootstrap"] = "ai"
    tags: list[str] = Field(default_factory=list, max_length=30)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    last_verified_at: datetime | None = None


class ConstraintPatch(BaseModel):
    expected_version: int | None = Field(None, ge=1)
    title: str | None = Field(None, min_length=1, max_length=256)
    statement: str | None = Field(None, min_length=1, max_length=100_000)
    rationale: str | None = Field(None, max_length=100_000)
    kind: ConstraintKind | None = None
    status: ConstraintStatus | None = None
    stability: ConstraintStability | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    tags: list[str] | None = Field(None, max_length=30)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    last_verified_at: datetime | None = None
    superseded_by: uuid.UUID | None = None


class ConstraintEdgeCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    source_constraint_id: uuid.UUID
    target_constraint_id: uuid.UUID
    relation: Literal["depends_on", "conflicts_with", "refines", "supersedes", "impacts"]
    reason: str | None = Field(None, max_length=10_000)
    created_by: Literal["manual", "ai", "imported", "bootstrap"] = "ai"
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    invalidated_at: datetime | None = None
    source_metadata: dict = Field(default_factory=dict)


class ConstraintEvidenceCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    constraint_id: uuid.UUID
    artifact_id: uuid.UUID
    relation: Literal[
        "originates_from", "implemented_by", "verified_by", "discussed_in", "violated_by"
    ]
    locator: dict = Field(default_factory=dict)
    excerpt: str | None = Field(None, max_length=20_000)
    created_by: Literal["manual", "ai", "imported", "bootstrap"] = "ai"
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    invalidated_at: datetime | None = None
    source_metadata: dict = Field(default_factory=dict)


class ProjectContextRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    task: str = Field(..., min_length=1, max_length=20_000)
    changed_paths: list[str] = Field(default_factory=list, max_length=200)
    limit: int = Field(20, ge=1, le=100)
    mode: Literal["local", "overview", "impact"] = "local"
    token_budget: int = Field(6000, ge=256, le=50_000)
    as_of: datetime | None = None
    valid_at: datetime | None = None
    record_run: bool = True
    shadow: bool = False
    request_id: str | None = Field(None, max_length=64)
    client: str | None = Field(None, max_length=64)
    client_version: str | None = Field(None, max_length=64)
    route: Literal["project", "impact", "temporal"] | None = None
    fallback: str | None = Field(None, max_length=32)
    error_code: str | None = Field(None, max_length=64)


class ProjectImpactRequest(ProjectContextRequest):
    constraint_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    depth: int = Field(2, ge=0, le=4)


class ArtifactChunkRebuildRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    artifact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    include_embeddings: bool = True
    limit: int = Field(200, ge=1, le=1000)
    after_path: str | None = Field(None, max_length=1024)
    missing_only: bool = False


class ConstraintEmbeddingRebuildRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    constraint_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    limit: int = Field(200, ge=1, le=1000)


class KnowledgeViewCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    kind: Literal["summary", "mental_model", "community"] = "summary"
    query: str | None = Field(None, max_length=20_000)
    content: str = Field(..., min_length=1, max_length=500_000)
    source_watermark: dict = Field(default_factory=dict)
    refresh_mode: Literal["manual", "derived"] = "manual"
    producer: str = Field("client", min_length=1, max_length=64)
    supersedes_id: uuid.UUID | None = None


class RevalidationProposalCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    constraint_id: uuid.UUID
    base_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=100_000)
    proposal: dict = Field(default_factory=dict)
    source_refs: list[dict] = Field(default_factory=list, max_length=200)
    idempotency_key: str = Field(..., min_length=1, max_length=128)
    created_by: Literal["manual", "ai", "imported", "bootstrap"] = "ai"


class RevalidationApplyRequest(BaseModel):
    expected_base_version: int = Field(..., ge=1)
    changes: ConstraintPatch


class EventLinkCreate(BaseModel):
    target_type: Literal["memory", "constraint", "artifact", "event"]
    target_id: uuid.UUID
    relation: str = Field(..., min_length=1, max_length=32)
    metadata: dict = Field(default_factory=dict)


class ProjectEventCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    event_type: Literal[
        "issue", "attempt", "failure", "fix", "decision", "test_result", "deploy", "note"
    ]
    title: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, max_length=500_000)
    occurred_at: datetime | None = None
    source: str = Field("client", min_length=1, max_length=32)
    source_ref: str | None = Field(None, max_length=2048)
    metadata: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(None, min_length=1, max_length=128)
    links: list[EventLinkCreate] = Field(default_factory=list, max_length=100)


class ProjectPreflightRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    task: str = Field(..., min_length=1, max_length=20_000)
    changed_paths: list[str] = Field(default_factory=list, max_length=200)
    planned_actions: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(20, ge=1, le=100)


class ContextQualityEvalRequest(BaseModel):
    results: list[dict] = Field(..., min_length=1, max_length=1000)
    k: int = Field(10, ge=1, le=100)


class ContextQualitySnapshotCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    k: int = Field(10, ge=1, le=100)
    trigger: Literal["manual", "background", "ci"] = "manual"
    dry_run: bool = True
    idempotency_key: str = Field(..., min_length=1, max_length=128)

    model_config = {"extra": "forbid"}


class AutomationProposalRunCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    dry_run: bool = True
    required_snapshots: int = Field(3, ge=2, le=10)
    include_sleep: bool = True
    include_revalidation: bool = True
    idempotency_key: str = Field(..., min_length=1, max_length=128)
