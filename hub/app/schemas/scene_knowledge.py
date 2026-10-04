"""Text-first scene knowledge contracts; metadata supports traceability."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EntryCategory = Literal["fact", "observation", "caution", "work"]
EntryStatus = Literal["active", "needs_review", "archived"]


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("Evidence time must include a timezone")
    return value


class SceneKnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(..., min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    title: str = Field(..., min_length=1, max_length=256)
    summary: str = Field("", max_length=5000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    project_id: str | None = Field(None, min_length=1, max_length=128)

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str]) -> list[str]:
        aliases = [value.strip() for value in values]
        if any(not value or len(value) > 128 for value in aliases):
            raise ValueError("Aliases must be nonempty and at most 128 characters")
        if len({value.casefold() for value in aliases}) != len(aliases):
            raise ValueError("Aliases must be unique")
        return aliases


class SceneEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: EntryCategory
    content: str = Field(..., min_length=1, max_length=20_000)
    source_ref: str = Field(..., min_length=1, max_length=2048)
    evidence_at: datetime | None = None
    status: Literal["active", "needs_review"] = "active"

    @field_validator("evidence_at")
    @classmethod
    def aware_evidence(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def atomic_entry(self) -> "SceneEntryCreate":
        self.content = self.content.strip()
        self.source_ref = self.source_ref.strip()
        if not self.content or not self.source_ref:
            raise ValueError("Content and source_ref must contain text")
        if self.category in {"fact", "observation", "caution"} and (
            "\n" in self.content or len(self.content) > 1000
        ):
            raise ValueError("Facts, observations, and cautions must be one concise item")
        if self.category in {"fact", "observation"} and self.evidence_at is None:
            raise ValueError("Facts and observations require a dated source")
        return self


class SceneEntryBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[SceneEntryCreate] = Field(..., min_length=1, max_length=100)


class SceneEntryCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=2000)
    source_ref: str = Field(..., min_length=1, max_length=2048)
    content: str | None = Field(None, min_length=1, max_length=20_000)
    evidence_at: datetime | None = None
    status: EntryStatus | None = None
    validations: list["SopValidation"] | None = None

    @field_validator("evidence_at")
    @classmethod
    def aware_evidence(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def meaningful_change(self) -> "SceneEntryCorrection":
        if self.content is None and self.status is None and self.evidence_at is None:
            raise ValueError("Correction needs content, status, or evidence_at")
        if not self.reason.strip() or not self.source_ref.strip():
            raise ValueError("Correction needs reason and source_ref")
        return self


class SopValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executed_at: datetime
    session_id: str = Field(..., min_length=1, max_length=128)
    conditions: str = Field(..., min_length=1, max_length=2000)
    observed_result: str = Field(..., min_length=1, max_length=2000)
    evidence_ref: str = Field(..., min_length=1, max_length=2048)
    result: Literal["effective"]

    @field_validator("executed_at")
    @classmethod
    def aware_execution(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Execution time must include a timezone")
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Execution time cannot be in the future")
        return value

    @field_validator("session_id", "conditions", "observed_result", "evidence_ref")
    @classmethod
    def nonblank_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Validation references must contain text")
        return normalized


def validate_sop(content: str, validations: list[SopValidation]) -> None:
    """The evidence gate is mechanical; clients must still assess real effectiveness."""
    sections = {
        "purpose": ("目的", "Purpose"),
        "applicability": ("适用", "Applicability"),
        "tools": ("工具", "Tools"),
        "steps": ("步骤", "Steps"),
        "acceptance": ("验收", "Acceptance"),
        "evidence": ("验证依据", "Validation evidence"),
    }
    lines = [line.lstrip("# ").strip().casefold() for line in content.splitlines()]
    missing = [
        name
        for name, labels in sections.items()
        if not any(any(line.startswith(label.casefold()) for label in labels) for line in lines)
    ]
    if missing or len(content.strip()) < 100:
        raise ValueError(f"SOP needs detailed sections: {', '.join(missing)}")
    if len(validations) < 3:
        raise ValueError("SOP needs at least three independent effective executions")
    if len({item.session_id for item in validations}) < 2:
        raise ValueError("SOP validations must span at least two sessions")
    if len({item.evidence_ref for item in validations}) != len(validations):
        raise ValueError("SOP validation evidence references must be distinct")
    if len({item.executed_at for item in validations}) != len(validations):
        raise ValueError("SOP validation times must be distinct")


class SceneSopPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=100, max_length=20_000)
    source_ref: str = Field(..., min_length=1, max_length=2048)
    validations: list[SopValidation] = Field(..., min_length=3, max_length=30)
    candidate_entry_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def admitted(self) -> "SceneSopPublish":
        self.content = self.content.strip()
        self.source_ref = self.source_ref.strip()
        if not self.source_ref:
            raise ValueError("SOP source_ref must contain text")
        validate_sop(self.content, self.validations)
        return self
