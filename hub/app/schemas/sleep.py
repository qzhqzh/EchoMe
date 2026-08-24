"""Schemas for memory sleep planning and apply APIs."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.memory import MemoryLayer, MemoryStatus, MemoryType, ScopeSchema

SleepMode = Literal["server_generated", "client_generated"]
SleepSessionStatus = Literal["draft", "proposed", "approved", "applied", "rejected"]
SleepCandidateStatus = Literal["active", "ai_review", "pending"]
SleepRequestedStatus = Literal["active", "ai_review", "pending", "deprecated", "archived"]
DEFAULT_CANDIDATE_STATUSES: list[SleepCandidateStatus] = ["active", "ai_review", "pending"]
ELIGIBLE_CANDIDATE_STATUSES = frozenset(DEFAULT_CANDIDATE_STATUSES)


def _default_candidate_statuses() -> list[SleepRequestedStatus]:
    return ["active", "ai_review", "pending"]


class SleepCandidatesRequest(BaseModel):
    """Request candidate memories for a client-generated sleep plan."""

    project_id: str | None = None
    session_id: uuid.UUID | None = None
    scope: Literal["project", "global", "all"] = "project"
    status: list[SleepRequestedStatus] = Field(default_factory=_default_candidate_statuses)
    page_size: int = Field(100, ge=1, le=500)
    cursor: int | None = Field(None, ge=0)
    include_protected: bool = True
    plan_schema_version: Literal["memory_sleep_plan.v1", "memory_sleep_plan.v2"] = (
        "memory_sleep_plan.v1"
    )


class SleepMemoryItem(BaseModel):
    """Memory payload returned to clients for planning."""

    id: uuid.UUID
    title: str
    content: str
    type: MemoryType
    layer: MemoryLayer
    priority: int
    tags: list[str]
    status: MemoryStatus
    source: str
    scope: ScopeSchema
    is_core: bool
    sleep_state: str
    access_count: int
    last_accessed_at: datetime | None
    superseded_by: uuid.UUID | None
    derived_from: list[Any]
    created_at: datetime
    updated_at: datetime
    protection_reason: str | None = None


class SleepEdgeItem(BaseModel):
    """Existing relation edge relevant to a candidate set."""

    id: uuid.UUID
    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID
    relation: str
    reason: str | None = None
    sleep_session_id: uuid.UUID | None = None
    created_at: datetime


class SleepCandidatesResponse(BaseModel):
    """Candidate memories and planning metadata."""

    session_id: uuid.UUID
    project_id: str | None
    schema_version: str = "memory_sleep_plan.v1"
    supported_schema_versions: list[str] = Field(
        default_factory=lambda: ["memory_sleep_plan.v1", "memory_sleep_plan.v2"]
    )
    candidates: list[SleepMemoryItem]
    protected_memories: list[SleepMemoryItem]
    relation_edges: list[SleepEdgeItem]
    json_schema: dict[str, Any]
    next_cursor: int | None
    has_more: bool


class SleepProposalSubmitRequest(BaseModel):
    """Submit a text and JSON proposal for an existing sleep session."""

    text_proposal: str | None = None
    json_proposal: dict[str, Any]


class SleepApplyRequest(BaseModel):
    """Apply an approved proposal."""

    approved: bool


class SleepSessionResponse(BaseModel):
    """Sleep session response."""

    session_id: uuid.UUID
    status: SleepSessionStatus
    mode: SleepMode
    project_id: str | None
    candidate_memory_ids: list[str]
    text_proposal: str | None = None
    json_proposal: dict[str, Any] | None = None
    applied_at: datetime | None = None


class SleepApplyResponse(BaseModel):
    """Result after applying a sleep plan."""

    session_id: uuid.UUID
    status: Literal["applied"]
    created_memory_ids: list[uuid.UUID]
    updated_memory_ids: list[uuid.UUID]
    edge_ids: list[uuid.UUID]
