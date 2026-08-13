"""Schemas for the unified, read-only context runtime."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class UnifiedContextRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=20_000)
    project_hint: str | None = Field(None, max_length=2048)
    changed_paths: list[str] = Field(default_factory=list, max_length=200)
    mode: Literal["auto", "personal", "project", "impact", "temporal"] = "auto"
    token_budget: int = Field(6000, ge=256, le=50_000)
    limit: int = Field(20, ge=1, le=100)
    as_of: datetime | None = None
    valid_at: datetime | None = None
    record_run: bool = True
    request_id: str | None = Field(None, max_length=64)
    client: str | None = Field(None, max_length=64)
    client_version: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def validate_scope(self) -> "UnifiedContextRequest":
        if self.mode in {"project", "impact", "temporal"} and not self.project_hint:
            raise ValueError(f"project_hint is required for {self.mode} mode")
        if self.mode == "personal" and self.project_hint:
            raise ValueError("project_hint is not accepted in personal mode")
        return self
