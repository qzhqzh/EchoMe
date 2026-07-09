"""Schemas for memory feedback."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MemoryFeedbackRating(str, Enum):
    helpful = "helpful"
    irrelevant = "irrelevant"
    outdated = "outdated"
    conflicting = "conflicting"
    wrong = "wrong"
    important = "important"


class FeedbackConfidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class FeedbackUsedBy(str, Enum):
    ai = "ai"
    user = "user"
    system = "system"


class FeedbackSource(str, Enum):
    mcp = "mcp"
    web = "web"
    api = "api"


class MemoryFeedbackCreate(BaseModel):
    memory_id: uuid.UUID
    rating: MemoryFeedbackRating
    note: str | None = Field(None, max_length=4000)
    task_context: str | None = Field(None, max_length=4000)
    used_by: FeedbackUsedBy = FeedbackUsedBy.ai
    confidence: FeedbackConfidence = FeedbackConfidence.medium
    source: FeedbackSource = FeedbackSource.mcp


class MemoryFeedbackBatchCreate(BaseModel):
    items: list[MemoryFeedbackCreate] = Field(..., min_length=1, max_length=50)


class MemoryFeedbackResponse(BaseModel):
    id: uuid.UUID
    memory_id: uuid.UUID
    rating: MemoryFeedbackRating
    note: str | None
    task_context: str | None
    used_by: FeedbackUsedBy
    confidence: FeedbackConfidence
    source: FeedbackSource
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryFeedbackSummary(BaseModel):
    memory_id: uuid.UUID
    total: int
    ratings: dict[str, int]
    last_feedback_at: datetime | None


class MemoryFeedbackCreateResponse(BaseModel):
    feedback: MemoryFeedbackResponse
    summary: MemoryFeedbackSummary


class MemoryFeedbackBatchResponse(BaseModel):
    items: list[MemoryFeedbackCreateResponse]
