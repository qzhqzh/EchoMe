"""Reliability classification and context intervention policy tests."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.memory import Memory, MemoryEdge, MemoryFeedback
from app.models.project_knowledge import ProjectConstraint
from app.services.context_policy import (
    _assess_constraint,
    _assess_memory,
    _intervention,
    apply_context_policy,
)


def _memory(**changes) -> Memory:
    values = {
        "id": uuid.uuid4(),
        "user_id": "user",
        "title": "Project deployment rule",
        "content": "Deploy after tests pass.",
        "type": "project",
        "layer": "L1",
        "scope_global": False,
        "scope_projects": ["project"],
        "scope_exclude": [],
        "priority": 8,
        "tags": ["deployment"],
        "status": "active",
        "source": "manual",
        "sleep_state": "fresh",
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(changes)
    return Memory(**values)


def test_superseded_memory_is_historical_and_silent_for_current_queries() -> None:
    memory = _memory(status="archived", sleep_state="superseded")

    result = _assess_memory(
        memory,
        edges=[],
        feedback=[],
        activity={"project": datetime.now(timezone.utc)},
        now=datetime.now(timezone.utc),
    )

    assert result["support_state"] == "historical"
    assert _intervention("historical", mode="project", has_evidence=False)["action"] == "silent"
    assert (
        _intervention("historical", mode="temporal", has_evidence=False)["action"]
        == "inject_with_warning"
    )


def test_dormant_project_is_separate_from_stale_memory() -> None:
    memory = _memory()
    now = datetime.now(timezone.utc)

    result = _assess_memory(
        memory,
        edges=[],
        feedback=[],
        activity={"project": now - timedelta(days=200)},
        now=now,
    )

    assert result["classification"] == "environment_bound"
    assert result["support_state"] == "dormant_scope"
    assert "project_dormant_not_stale" in result["reason_codes"]


def test_explicit_conflict_wins_over_recency() -> None:
    memory = _memory()
    edge = MemoryEdge(
        id=uuid.uuid4(),
        user_id="user",
        source_memory_id=memory.id,
        target_memory_id=uuid.uuid4(),
        relation="conflicts_with",
        created_by="test",
    )
    feedback = MemoryFeedback(
        id=uuid.uuid4(),
        user_id="user",
        memory_id=memory.id,
        rating="helpful",
        used_by="user",
        confidence="high",
        source="web",
    )

    result = _assess_memory(
        memory,
        edges=[edge],
        feedback=[feedback],
        activity={"project": datetime.now(timezone.utc)},
        now=datetime.now(timezone.utc),
    )

    assert result["support_state"] == "conflicting"
    assert result["confidence"] == 0.9


def test_superseded_by_edge_only_marks_the_source_as_historical() -> None:
    source = _memory()
    replacement = _memory()
    edge = MemoryEdge(
        id=uuid.uuid4(),
        user_id="user",
        source_memory_id=source.id,
        target_memory_id=replacement.id,
        relation="superseded_by",
        created_by="test",
    )
    now = datetime.now(timezone.utc)

    source_result = _assess_memory(
        source,
        edges=[edge],
        feedback=[],
        activity={"project": now},
        now=now,
    )
    replacement_result = _assess_memory(
        replacement,
        edges=[edge],
        feedback=[],
        activity={"project": now},
        now=now,
    )

    assert source_result["support_state"] == "historical"
    assert replacement_result["support_state"] == "current_supported"


def test_proposed_constraint_requires_verification() -> None:
    now = datetime.now(timezone.utc)
    constraint = ProjectConstraint(
        id=uuid.uuid4(),
        user_id="user",
        project_id="project",
        title="Candidate rule",
        statement="Use a new release workflow.",
        kind="process",
        status="proposed",
        stability="evolving",
        confidence=0.7,
        version=1,
        created_at=now,
        updated_at=now,
    )

    result = _assess_constraint(
        constraint,
        conflicts=set(),
        stale_constraints=set(),
        evidence_refs=[],
        project_activity=now,
        valid_at=now,
        now=now,
    )

    assert result["support_state"] == "needs_verification"
    assert "status:proposed" in result["reason_codes"]


@pytest.mark.asyncio
async def test_enforce_request_falls_back_to_shadow_when_feature_is_disabled() -> None:
    context = {
        "memories": [],
        "constraints": [],
        "evidence": [],
        "conflicts": [],
        "stale_warnings": [],
        "unknowns": [],
        "retrieval_trace": {},
    }

    result = await apply_context_policy(
        AsyncMock(),
        user_id="user",
        context=context,
        requested_mode="enforce",
        enforce_enabled=False,
        persist_assessments=False,
    )

    assert result["context_policy"]["effective_mode"] == "shadow"
    assert result["context_policy"]["enforced"] is False
    assert result["context_policy"]["fallback_reason"] == "context_policy_enforce_disabled"


@pytest.mark.asyncio
async def test_enabled_enforce_withholds_historical_memory(monkeypatch) -> None:
    memory = _memory(status="archived", sleep_state="superseded")
    result_set = MagicMock()
    result_set.scalars.return_value.all.return_value = [memory]
    session = AsyncMock()
    session.execute.return_value = result_set
    monkeypatch.setattr(
        "app.services.context_policy._load_memory_signals",
        AsyncMock(return_value=({memory.id: []}, {memory.id: []})),
    )
    monkeypatch.setattr(
        "app.services.context_policy._project_activity",
        AsyncMock(return_value={"project": datetime.now(timezone.utc)}),
    )
    context = {
        "memories": [{"id": str(memory.id), "title": memory.title}],
        "constraints": [],
        "must_include": [],
        "evidence": [],
        "conflicts": [],
        "stale_warnings": [],
        "unknowns": [],
        "retrieval_trace": {},
    }

    result = await apply_context_policy(
        session,
        user_id="user",
        context=context,
        requested_mode="enforce",
        enforce_enabled=True,
        persist_assessments=False,
    )

    assert result["memories"] == []
    assert result["context_policy"]["excluded"]["memories"] == [str(memory.id)]
    assert result["context_policy"]["source_mutation"] == "none"
