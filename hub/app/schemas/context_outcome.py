"""Schemas for explicit context outcome signals."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ContextOutcomeCreate(BaseModel):
    context_run_id: uuid.UUID
    outcome: Literal["success", "partial", "failed", "corrected", "no_signal"]
    policy_effect: Literal["helpful", "neutral", "harmful", "uncertain"] | None = None
    reported_by: Literal["user", "ai", "system"] = "ai"
    source: Literal["mcp", "web", "api", "ci"] = "mcp"
    project_event_id: uuid.UUID | None = None
    note: str | None = Field(None, max_length=2000)
    idempotency_key: str = Field(..., min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key cannot be empty")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_evidence(self) -> "ContextOutcomeCreate":
        if self.outcome == "corrected" and not self.note:
            raise ValueError("corrected outcomes require a note")
        if self.policy_effect == "harmful" and not self.note:
            raise ValueError("harmful policy effects require a note")
        if (self.reported_by == "system" or self.source == "ci") and not self.project_event_id:
            raise ValueError("system and CI outcomes require a project_event_id")
        return self


class ContextOutcomeBatchCreate(BaseModel):
    items: list[ContextOutcomeCreate] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_idempotency_keys(self) -> "ContextOutcomeBatchCreate":
        keys = [(item.context_run_id, item.idempotency_key) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("batch contains duplicate context run idempotency keys")
        return self
