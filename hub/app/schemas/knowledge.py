"""Strict write contracts for the knowledge workbench. No client attestation fields."""

import math
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
ShortText = Annotated[str, StringConstraints(max_length=4000)]
Body = Annotated[str, StringConstraints(max_length=200000)]
Kind = Literal[
    "project",
    "question",
    "entity",
    "relation",
    "predicate",
    "page",
    "source",
    "placement",
    "usage",
    "deliverable",
    "review",
    "acceptance",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectData(StrictModel):
    name: Title
    summary: ShortText = ""
    status: Literal["draft", "active", "ready_for_review", "delivered", "archived"] = "draft"


class QuestionData(StrictModel):
    title: Title
    project_id: UUID | None = None
    status: Literal["open", "investigating", "resolved", "archived"] = "open"
    resolution_note: ShortText = ""
    answer_page_id: UUID | None = None
    answer_page_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_answer(self) -> "QuestionData":
        if bool(self.answer_page_id) != bool(self.answer_page_revision):
            raise ValueError("answer_page_id and answer_page_revision must be supplied together")
        if self.status == "resolved" and not (self.resolution_note.strip() or self.answer_page_id):
            raise ValueError("Resolving a question requires an answer or a closing reason")
        return self


class EntityData(StrictModel):
    name: Title
    entity_kind: Literal["topic", "concept", "tool", "method", "object"] = "concept"
    summary: ShortText = ""
    aliases: list[Title] = Field(default_factory=list, max_length=30)
    attributes: dict[str, Any] = Field(default_factory=dict)
    personal_note: ShortText = ""
    status: Literal["active", "archived", "merged"] = "active"
    merged_into_id: UUID | None = None


class PredicateData(StrictModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    label: Title
    description: ShortText = ""
    family: Literal["navigation", "assertion"] = "assertion"
    value_kind: Literal["entity", "scalar"] = "entity"
    status: Literal["active", "archived"] = "active"


class Scalar(StrictModel):
    type: Literal["string", "number", "boolean", "date"]
    value: str | float | bool

    @model_validator(mode="before")
    @classmethod
    def check_type(cls, value: Any) -> Any:
        if isinstance(value, dict):
            kind, raw = value.get("type"), value.get("value")
            valid = (
                (kind in ("string", "date") and isinstance(raw, str))
                or (kind == "number" and type(raw) in (int, float))
                or (kind == "boolean" and type(raw) is bool)
            )
            if not valid:
                raise ValueError("Scalar value does not match its type")
            if kind == "number" and isinstance(raw, (int, float)) and not math.isfinite(raw):
                raise ValueError("Numeric values must be finite")
            if kind == "date" and isinstance(raw, str):
                datetime.fromisoformat(raw)
        return value


class Evidence(StrictModel):
    source_id: UUID
    source_revision: int = Field(ge=1)
    locator: ShortText
    quote: ShortText = ""
    role: Literal["supports", "refutes", "context"] = "context"


class RelationData(StrictModel):
    subject_id: UUID
    predicate_id: UUID
    object_entity_id: UUID | None = None
    object_value: Scalar | None = None
    statement_md: ShortText = ""
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    perspective: Literal["general", "personal", "unspecified"] = "unspecified"
    status: Literal["active", "archived"] = "active"
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def check_object(self) -> "RelationData":
        if (self.object_entity_id is None) == (self.object_value is None):
            raise ValueError("Exactly one of object_entity_id and object_value is required")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        return self


class Binding(StrictModel):
    target_id: UUID
    role: Literal["overview", "supplementary"] = "supplementary"


class PageData(StrictModel):
    title: Title
    body_md: Body = ""
    bindings: list[Binding] = Field(default_factory=list, max_length=50)
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def check_bindings(self) -> "PageData":
        if len({b.target_id for b in self.bindings}) != len(self.bindings):
            raise ValueError("Duplicate page binding")
        if sum(b.role == "overview" for b in self.bindings) > 1:
            raise ValueError("A page can be the overview of at most one object")
        return self


class SourceData(StrictModel):
    title: Title
    context_ids: list[UUID] = Field(default_factory=list, max_length=50)
    source_kind: Literal["url", "file", "publication", "page", "practice"] = "url"
    origin_ref: ShortText = ""
    author: Title | None = None
    published_at: AwareDatetime | None = None
    accessed_at: AwareDatetime | None = None
    retention: Literal["reference", "excerpt", "snapshot", "internal_version"] = "reference"
    content_text: Body = ""
    page_id: UUID | None = None
    page_revision: int | None = Field(default=None, ge=1)
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def check_capture(self) -> "SourceData":
        if self.retention == "internal_version":
            if not self.page_id or not self.page_revision or self.content_text:
                raise ValueError("Internal source must pin a Page version without copying its body")
        elif self.page_id or self.page_revision:
            raise ValueError("Page references require internal_version retention")
        if self.retention == "reference" and self.content_text:
            raise ValueError("Reference retention cannot claim saved content")
        if self.retention in ("excerpt", "snapshot") and not self.content_text.strip():
            raise ValueError("Saved content is required for excerpt/snapshot retention")
        return self


class PlacementData(StrictModel):
    entity_id: UUID
    parent_id: UUID | None = None
    sort_order: int = 0
    status: Literal["active", "archived"] = "active"


class UsageData(StrictModel):
    context_id: UUID
    knowledge_id: UUID
    knowledge_revision: int = Field(ge=1)
    role: Literal["to_research", "used", "derived"] = "used"
    application_note: ShortText = ""
    page_id: UUID | None = None
    page_revision: int | None = Field(default=None, ge=1)
    deliverable_id: UUID | None = None
    deliverable_revision: int | None = Field(default=None, ge=1)
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def paired_versions(self) -> "UsageData":
        for name in ("page", "deliverable"):
            if bool(getattr(self, name + "_id")) != bool(getattr(self, name + "_revision")):
                raise ValueError(f"{name}_id and {name}_revision must be supplied together")
        return self


class DeliverableData(StrictModel):
    title: Title
    project_id: UUID | None = None
    question_id: UUID | None = None
    resource_ref: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    preview_refs: list[ShortText] = Field(default_factory=list, max_length=12)
    format: Annotated[str, StringConstraints(max_length=64)] = ""
    produced_at: AwareDatetime | None = None
    reproduction_page_id: UUID | None = None
    reproduction_page_revision: int | None = Field(default=None, ge=1)
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def check_context(self) -> "DeliverableData":
        if not (self.project_id or self.question_id):
            raise ValueError("Deliverable needs a project or question")
        if bool(self.reproduction_page_id) != bool(self.reproduction_page_revision):
            raise ValueError("Reproduction Page must be pinned to a revision")
        return self


class Target(StrictModel):
    id: UUID
    revision: int = Field(ge=1)


class Proposal(StrictModel):
    operation: Literal["none", "update", "merge", "archive", "verify"] = "none"
    target_id: UUID | None = None
    into_id: UUID | None = None
    patch: dict[str, Any] = Field(default_factory=dict)


class ReviewData(StrictModel):
    title: Title
    issue_kind: Literal[
        "duplicate",
        "conflict",
        "overgeneralization",
        "page_mismatch",
        "fragmentation",
        "verification",
    ]
    explanation: ShortText
    targets: list[Target] = Field(min_length=1, max_length=10)
    proposal: Proposal = Field(default_factory=Proposal)
    status: Literal["open", "snoozed", "resolved", "dismissed", "disputed"] = "open"
    resolution_note: ShortText = ""


class AcceptanceData(StrictModel):
    deliverable_id: UUID
    deliverable_revision: int = Field(ge=1)
    criteria_page_id: UUID | None = None
    criteria_page_revision: int | None = Field(default=None, ge=1)
    state: Literal["submitted", "accepted", "rejected"] = "submitted"
    checks: ShortText = ""
    note: ShortText = ""
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def check_criteria(self) -> "AcceptanceData":
        if bool(self.criteria_page_id) != bool(self.criteria_page_revision):
            raise ValueError("Criteria Page must be pinned to a revision")
        if self.state != "submitted" and not self.criteria_page_id:
            raise ValueError("Acceptance decisions require versioned criteria")
        return self


CONTRACTS: dict[str, type[StrictModel]] = {
    "project": ProjectData,
    "question": QuestionData,
    "entity": EntityData,
    "predicate": PredicateData,
    "relation": RelationData,
    "page": PageData,
    "source": SourceData,
    "placement": PlacementData,
    "usage": UsageData,
    "deliverable": DeliverableData,
    "review": ReviewData,
    "acceptance": AcceptanceData,
}


class RecordCreate(StrictModel):
    kind: Kind
    data: dict[str, Any]
    existing_project_id: str | None = Field(default=None, max_length=128)
    reason: ShortText = ""


class RecordUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    data: dict[str, Any]
    reason: ShortText = ""


class CapturePlacement(StrictModel):
    parent_id: UUID | None = None


class PlacementRemoval(StrictModel):
    expected_revision: int = Field(ge=1)


class KnowledgeCapture(StrictModel):
    record: RecordCreate
    placement: CapturePlacement | None = None
    context_id: UUID | None = None
    first_question: Title | None = None


class ReviewDecisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal[
        "apply", "keep_distinct", "dismiss", "snooze", "reopen", "dispute", "request_evidence"
    ]
    note: ShortText = ""


class KnowledgeQuery(StrictModel):
    kind: Kind = "relation"
    filters: dict[str, Any] = Field(default_factory=dict)
    exclude_entity_kind: Literal["topic", "concept", "tool", "method", "object"] | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    include_inactive: bool = False


class TokenCreate(StrictModel):
    name: Title
