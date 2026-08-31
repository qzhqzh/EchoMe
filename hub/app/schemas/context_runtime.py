"""Schemas for the unified, read-only context runtime."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class UnifiedContextRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=20_000)
    project_hint: str | None = Field(None, max_length=2048)
    project_hints: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(
        default_factory=list,
        max_length=10,
    )
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
    policy_mode: Literal["off", "shadow", "enforce"] = "shadow"

    @model_validator(mode="after")
    def validate_scope(self) -> "UnifiedContextRequest":
        has_project_hint = bool(
            (self.project_hint and self.project_hint.strip())
            or any(hint.strip() for hint in self.project_hints)
        )
        if self.mode in {"project", "impact", "temporal"} and not has_project_hint:
            raise ValueError(f"project_hint or project_hints is required for {self.mode} mode")
        if self.mode == "personal" and has_project_hint:
            raise ValueError("project hints are not accepted in personal mode")
        return self
