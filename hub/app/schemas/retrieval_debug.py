"""Schemas for retrieval debugger."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RetrievalDebugRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    status: str = "active"
    project_id: str | None = None
    limit: int = Field(10, ge=1, le=50)
    expected_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    client: str = Field("web", max_length=32)
    source: str = Field("debugger", max_length=32)


class RetrievalLogCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    client: str = Field("mcp", max_length=32)
    source: str = Field("search_summary", max_length=32)
    status: str | None = None
    project_id: str | None = None
    limit: int = Field(10, ge=1, le=50)
    lightweight_count: int = Field(0, ge=0)
    semantic_count: int = Field(0, ge=0)
    fallback_used: bool = False
    expected_ids: list[str] = Field(default_factory=list, max_length=20)
    expected_rank: int | None = None
    top_results: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class RetrievalLogResponse(BaseModel):
    id: uuid.UUID
    query: str
    client: str
    source: str
    status_filter: str | None
    project_id: str | None
    limit: int
    lightweight_count: int
    semantic_count: int
    fallback_used: bool
    expected_ids: list[str]
    expected_rank: int | None
    top_results: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class RetrievalLogListResponse(BaseModel):
    total: int
    items: list[RetrievalLogResponse]
