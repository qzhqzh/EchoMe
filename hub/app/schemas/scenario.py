"""Validated contracts for reusable scenarios and continuing work."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Slug = str


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(..., min_length=1, max_length=500)
    required: bool = True
    secret: bool = False
    default: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def no_secret_default(self) -> "ScenarioInput":
        if self.secret and self.default is not None:
            raise ValueError("secret inputs cannot have stored defaults")
        return self


class ScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicability: str = Field(..., min_length=1, max_length=5000)
    exclusions: str = Field(..., min_length=1, max_length=5000)
    input_fields: list[ScenarioInput] = Field(default_factory=list, max_length=40)
    required_environment: dict[str, str] = Field(default_factory=dict)
    steps: list[str] = Field(..., min_length=1, max_length=80)
    verification: list[str] = Field(..., min_length=1, max_length=40)
    recovery: list[str] = Field(..., min_length=1, max_length=40)
    execution_ref: str | None = Field(None, max_length=2048)
    source_refs: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_definition(self) -> "ScenarioDefinition":
        names = [field.name for field in self.input_fields]
        if len(names) != len(set(names)):
            raise ValueError("input field names must be unique")
        if len(self.required_environment) > 30:
            raise ValueError("required_environment has too many entries")
        if any(
            not key or len(key) > 64 or not value or len(value) > 256
            for key, value in self.required_environment.items()
        ):
            raise ValueError("required_environment keys and values must be nonempty and bounded")
        for entry in [*self.steps, *self.verification, *self.recovery, *self.source_refs]:
            if not entry.strip() or len(entry) > 5000:
                raise ValueError("procedure entries must be nonempty and at most 5000 characters")
        return self


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug = Field(..., min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    title: str = Field(..., min_length=1, max_length=256)
    summary: str = Field(..., min_length=1, max_length=5000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    project_id: str | None = Field(None, min_length=1, max_length=128)
    definition: ScenarioDefinition

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, aliases: list[str]) -> list[str]:
        normalized = [alias.strip() for alias in aliases]
        if any(not alias or len(alias) > 128 for alias in normalized):
            raise ValueError("aliases must be nonempty and at most 128 characters")
        if len({alias.casefold() for alias in normalized}) != len(normalized):
            raise ValueError("aliases must be unique")
        return normalized


class ScenarioPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=256)
    summary: str | None = Field(None, min_length=1, max_length=5000)
    aliases: list[str] | None = Field(None, max_length=20)
    enabled: bool | None = None

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, aliases: list[str] | None) -> list[str] | None:
        return ScenarioCreate.clean_aliases(aliases) if aliases is not None else None


class ScenarioVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: ScenarioDefinition


class ScenarioPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_evidence: str = Field(..., min_length=1, max_length=20_000)


class ScenarioResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: str = Field(..., min_length=1, max_length=128)
    parameters: dict[str, str] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)


class ScenarioItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_slug: str | None = Field(None, min_length=1, max_length=128)
    version: int | None = Field(None, ge=1)
    title: str = Field(..., min_length=1, max_length=256)
    goal: str = Field(..., min_length=1, max_length=5000)
    working_plan: str | None = Field(None, min_length=1, max_length=20_000)
    mode: Literal["one_off", "continuous"] = "one_off"
    phase: str = Field("ready", min_length=1, max_length=128)
    state: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, str] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    next_check_at: datetime | None = None

    @model_validator(mode="after")
    def require_plan_or_scenario(self) -> "ScenarioItemCreate":
        if self.scenario_slug is None and not (self.working_plan or "").strip():
            raise ValueError("standalone items require a working_plan")
        if self.scenario_slug is not None and self.working_plan is not None:
            raise ValueError("scenario-bound items use the published definition")
        if self.scenario_slug is None and self.version is not None:
            raise ValueError("standalone items cannot select a scenario version")
        return self

    @field_validator("working_plan")
    @classmethod
    def nonblank_plan(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("working_plan must contain text")
        return value

    @field_validator("next_check_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("next_check_at must include a timezone")
        return value


class ScenarioItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    status: Literal["active", "paused", "completed"] | None = None
    phase: str | None = Field(None, min_length=1, max_length=128)
    state: dict[str, Any] | None = None
    working_plan: str | None = Field(None, min_length=1, max_length=20_000)
    next_check_at: datetime | None = None

    @field_validator("next_check_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        return ScenarioItemCreate.aware_time(value)

    @field_validator("working_plan")
    @classmethod
    def nonblank_plan(cls, value: str | None) -> str | None:
        return ScenarioItemCreate.nonblank_plan(value)


class ScenarioItemUpgrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=5000)


class ScenarioItemBind(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    scenario_slug: str = Field(..., min_length=1, max_length=128)
    version: int | None = Field(None, ge=1)
    reason: str = Field(..., min_length=1, max_length=5000)
    parameters: dict[str, str] | None = None
    environment: dict[str, str] | None = None


class ScenarioClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=1, max_length=128)
    lease_seconds: int = Field(300, ge=30, le=3600)
    force: bool = False


class ScenarioRunFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: uuid.UUID
    outcome: Literal["success", "failure", "skipped"]
    observation: Literal["normal", "alert", "unknown"] = "unknown"
    summary: str = Field(..., min_length=1, max_length=10_000)
    evidence: list[str] = Field(default_factory=list, max_length=30)
    event_key: str | None = Field(None, min_length=1, max_length=128)
    action_required: bool = False
    phase: str | None = Field(None, min_length=1, max_length=128)
    state: dict[str, Any] | None = None
    next_check_at: datetime | None = None
    complete_item: bool = False

    @model_validator(mode="after")
    def validate_outcome(self) -> "ScenarioRunFinish":
        if self.outcome == "success" and self.observation == "unknown":
            raise ValueError("successful checks require a normal or alert observation")
        if self.outcome != "success" and self.observation != "unknown":
            raise ValueError("failed or skipped checks have an unknown observation")
        if self.complete_item and self.outcome != "success":
            raise ValueError("only a successful run can complete an item")
        if self.next_check_at is not None and self.next_check_at.tzinfo is None:
            raise ValueError("next_check_at must include a timezone")
        if any(not item.strip() or len(item) > 2048 for item in self.evidence):
            raise ValueError("evidence entries must be nonempty and at most 2048 characters")
        return self
