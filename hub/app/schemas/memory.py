"""Pydantic schemas for API request/response validation."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class MemoryType(str, Enum):
    identity = "identity"
    method = "method"
    stack = "stack"
    guardrail = "guardrail"
    template = "template"
    decision = "decision"
    context = "context"
    style = "style"
    project = "project"
    reasoning = "reasoning"


class MemoryLayer(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class MemoryStatus(str, Enum):
    active = "active"
    ai_review = "ai_review"
    pending = "pending"
    deprecated = "deprecated"
    archived = "archived"


class MemorySource(str, Enum):
    manual = "manual"
    ai_suggested = "ai_suggested"
    imported = "imported"


class ScopeSchema(BaseModel):
    """Memory scope definition."""

    global_: bool = Field(True, alias="global", serialization_alias="global")
    projects: list[str] = Field(default_factory=list)
    exclude_projects: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# --- Request Schemas ---


class Visibility(str, Enum):
    private = "private"
    public = "public"


class MemoryCreate(BaseModel):
    """Request body for creating a memory."""

    title: str = Field(..., max_length=256)
    content: str = Field(..., max_length=100000)
    type: MemoryType
    layer: MemoryLayer = MemoryLayer.L2
    priority: int = Field(5, ge=1, le=10)
    tags: list[str] = Field(default_factory=list, max_length=20)
    status: MemoryStatus = MemoryStatus.active
    scope: ScopeSchema = Field(default_factory=ScopeSchema)
    source: MemorySource = MemorySource.manual
    visibility: Visibility = Visibility.private


class MemoryUpdate(BaseModel):
    """Request body for full update."""

    title: str = Field(..., max_length=256)
    content: str = Field(..., max_length=100000)
    type: MemoryType
    layer: MemoryLayer
    priority: int = Field(..., ge=1, le=10)
    tags: list[str]
    status: MemoryStatus
    scope: ScopeSchema
    source: MemorySource
    visibility: Visibility = Visibility.private


class MemoryPatch(BaseModel):
    """Request body for partial update."""

    title: str | None = Field(None, max_length=256)
    content: str | None = None
    type: MemoryType | None = None
    layer: MemoryLayer | None = None
    priority: int | None = Field(None, ge=1, le=10)
    tags: list[str] | None = None
    status: MemoryStatus | None = None
    scope: ScopeSchema | None = None
    source: MemorySource | None = None
    visibility: Visibility | None = None


class MemorySearchRequest(BaseModel):
    """Request body for memory search."""

    query: str
    type: MemoryType | None = None
    layer: MemoryLayer | None = None
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    top_k: int = Field(5, ge=1, le=20)
    min_score: float = Field(0.3, ge=0.0, le=1.0)


# --- Response Schemas ---


class _OrmScopeMixin:
    """Mixin to convert flat ORM scope fields into nested ScopeSchema."""

    @model_validator(mode="before")
    @classmethod
    def build_scope_from_orm(cls, data: Any) -> Any:
        """Convert scope_global/scope_projects/scope_exclude → scope dict."""
        if hasattr(data, "scope_global"):
            # It's an ORM object — convert to dict with nested scope
            return {
                "id": data.id,
                "title": data.title,
                "content": getattr(data, "content", None),
                "type": data.type,
                "layer": data.layer,
                "priority": data.priority,
                "tags": data.tags,
                "status": data.status,
                "source": data.source,
                "token_count": data.token_count,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
                "visibility": getattr(data, "visibility", "private"),
                "forked_from": getattr(data, "forked_from", None),
                "scope": {
                    "global": data.scope_global,
                    "projects": data.scope_projects,
                    "exclude_projects": data.scope_exclude,
                },
            }
        return data


class MemoryResponse(_OrmScopeMixin, BaseModel):
    """Full memory response."""

    id: uuid.UUID
    title: str
    content: str
    type: MemoryType
    layer: MemoryLayer
    priority: int
    tags: list[str]
    status: MemoryStatus
    scope: ScopeSchema
    source: MemorySource
    token_count: int
    visibility: Visibility = Visibility.private
    forked_from: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryListItem(_OrmScopeMixin, BaseModel):
    """Memory item in list responses (without full content)."""

    id: uuid.UUID
    title: str
    type: MemoryType
    layer: MemoryLayer
    priority: int
    tags: list[str]
    status: MemoryStatus
    scope: ScopeSchema
    source: MemorySource
    token_count: int
    visibility: Visibility = Visibility.private
    forked_from: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryListResponse(BaseModel):
    """Paginated list of memories."""

    total: int
    offset: int
    limit: int
    items: list[MemoryListItem]


class MemoryCreateResponse(BaseModel):
    """Response after creating a memory."""

    id: uuid.UUID
    title: str
    token_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchResultItem(BaseModel):
    """Single search result."""

    id: uuid.UUID
    title: str
    content: str
    type: MemoryType
    layer: MemoryLayer
    score: float
    tags: list[str]


class SearchResponse(BaseModel):
    """Search results."""

    results: list[SearchResultItem]
    total_searched: int


# --- Sync Schemas ---


class SyncPushItem(BaseModel):
    """A single memory in a push request."""

    id: uuid.UUID | None = None
    title: str
    content: str
    type: MemoryType
    layer: MemoryLayer
    priority: int = Field(5, ge=1, le=10)
    tags: list[str] = Field(default_factory=list)
    status: MemoryStatus = MemoryStatus.active
    scope: ScopeSchema = Field(default_factory=ScopeSchema)
    source: MemorySource = MemorySource.manual
    visibility: Visibility = Visibility.private
    updated_at: datetime | None = None


class SyncPushRequest(BaseModel):
    """Request body for push sync."""

    memories: list[SyncPushItem]
    client_info: str | None = None


class SyncPushResponse(BaseModel):
    """Response for push sync."""

    created: int
    updated: int
    unchanged: int
    conflicts: list[str]


class SyncPullRequest(BaseModel):
    """Request body for pull sync."""

    since: datetime | None = None
    include_pending: bool = True


class SyncPullResponse(BaseModel):
    """Response for pull sync."""

    memories: list[MemoryResponse]
    total: int
    server_time: datetime


# --- Render Schema ---


class RenderRequest(BaseModel):
    """Request for rendering memories into target format."""

    target: str = Field(..., description="Target CLI: 'claude' or 'codex'")
    project_id: str | None = None
    layer: MemoryLayer | None = None
    format: str = "markdown"


class RenderResponse(BaseModel):
    """Rendered content for injection."""

    content: str
    token_count: int
    memories_included: int
    memories_truncated: int
