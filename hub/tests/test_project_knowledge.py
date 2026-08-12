"""Tests for project constraint graph selection and sync schemas."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.project_knowledge import (
    _context_shadow_comparison,
    _create_artifact_chunks,
    _select_impact_ids,
)
from app.models.project_knowledge import (
    ConstraintEdge,
    ConstraintEvidence,
    ProjectArtifact,
    ProjectConstraint,
)
from app.schemas.project_knowledge import ProjectImpactRequest
from app.services.context_compiler import (
    _trim_to_budget,
    constraint_document,
    query_tokens,
)


def test_impact_selection_starts_from_changed_artifact_and_traverses_edges() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    first = ProjectConstraint(
        id=first_id,
        user_id="user",
        project_id="EchoMe",
        title="Keep API compatible",
        statement="Existing API response fields must remain compatible.",
        kind="compatibility",
        status="active",
        stability="invariant",
        confidence=1,
        source="manual",
    )
    second = ProjectConstraint(
        id=second_id,
        user_id="user",
        project_id="EchoMe",
        title="MCP consumes Hub API",
        statement="MCP clients depend on Hub response contracts.",
        kind="architecture",
        status="active",
        stability="evolving",
        confidence=0.9,
        source="bootstrap",
    )
    artifact = ProjectArtifact(
        id=artifact_id,
        user_id="user",
        project_id="EchoMe",
        logical_path="hub/app/api/memories.py",
        kind="code",
        title="memories",
        content="content",
        content_hash="a" * 64,
        size_bytes=7,
    )
    evidence = ConstraintEvidence(
        user_id="user",
        project_id="EchoMe",
        constraint_id=first_id,
        artifact_id=artifact_id,
        relation="implemented_by",
    )
    edge = ConstraintEdge(
        user_id="user",
        project_id="EchoMe",
        source_constraint_id=first_id,
        target_constraint_id=second_id,
        relation="impacts",
    )
    body = ProjectImpactRequest(
        project_id="EchoMe",
        task="Change implementation",
        changed_paths=["hub/app/api/memories.py"],
        depth=1,
    )

    selected, reasons = _select_impact_ids([first, second], [artifact], [edge], [evidence], body)

    assert selected == {first_id, second_id}
    assert "linked_to_changed_artifact:implemented_by" in reasons[first_id]
    assert "graph:impacts:depth_1" in reasons[second_id]


def test_inactive_constraint_is_not_selected_by_text_alone() -> None:
    constraint = ProjectConstraint(
        id=uuid.uuid4(),
        user_id="user",
        project_id="EchoMe",
        title="Legacy deployment rule",
        statement="Use the legacy deployment path.",
        kind="process",
        status="deprecated",
        stability="temporary",
        confidence=1,
        source="manual",
    )
    body = ProjectImpactRequest(
        project_id="EchoMe",
        task="legacy deployment path",
        depth=0,
    )

    selected, _ = _select_impact_ids([constraint], [], [], [], body)

    assert selected == set()


def test_depends_on_propagates_from_dependency_to_dependent_only() -> None:
    dependent_id = uuid.uuid4()
    dependency_id = uuid.uuid4()
    dependent = ProjectConstraint(
        id=dependent_id,
        user_id="user",
        project_id="EchoMe",
        title="MCP context",
        statement="Context depends on the domain boundary.",
        kind="architecture",
        status="active",
        stability="evolving",
        confidence=1,
        source="manual",
    )
    dependency = ProjectConstraint(
        id=dependency_id,
        user_id="user",
        project_id="EchoMe",
        title="Domain boundary",
        statement="Memory and constraints remain separate.",
        kind="architecture",
        status="active",
        stability="invariant",
        confidence=1,
        source="manual",
    )
    edge = ConstraintEdge(
        user_id="user",
        project_id="EchoMe",
        source_constraint_id=dependent_id,
        target_constraint_id=dependency_id,
        relation="depends_on",
    )

    from_dependency, _ = _select_impact_ids(
        [dependent, dependency],
        [],
        [edge],
        [],
        ProjectImpactRequest(
            project_id="EchoMe", task="unrelated", constraint_ids=[dependency_id], depth=1
        ),
    )
    from_dependent, _ = _select_impact_ids(
        [dependent, dependency],
        [],
        [edge],
        [],
        ProjectImpactRequest(
            project_id="EchoMe", task="unrelated", constraint_ids=[dependent_id], depth=1
        ),
    )

    assert from_dependency == {dependency_id, dependent_id}
    assert from_dependent == {dependent_id}


def test_context_tokens_expand_cross_language_project_terms() -> None:
    tokens = query_tokens("为项目增加数据库表，如何迁移？")

    assert {"migration", "alembic", "additive"} <= tokens


def test_constraint_document_includes_typed_ontology_labels() -> None:
    constraint = ProjectConstraint(
        id=uuid.uuid4(),
        user_id="user",
        project_id="EchoMe",
        title="Additive changes",
        statement="Use a migration.",
        kind="process",
        status="active",
        stability="invariant",
        confidence=1,
        source="manual",
    )

    document = constraint_document(constraint)

    assert "migration" in document
    assert "流程迁移审核验证" in document


def test_token_budget_discards_standalone_chunks_before_constraints() -> None:
    pack = {
        "project": {"id": "EchoMe"},
        "task": "migration",
        "mode": "local",
        "must_include": [],
        "constraints": [{"id": "constraint", "statement": "keep this constraint"}],
        "memories": [],
        "artifacts": [{"id": "artifact"}],
        "evidence": [
            {
                "id": "chunk",
                "evidence_type": "artifact_chunk",
                "artifact_id": "artifact",
                "content": "large evidence " * 1000,
            }
        ],
        "conflicts": [],
        "stale_warnings": [],
        "unknowns": [],
        "token_budget": 500,
        "token_used": 0,
        "retrieval_trace": {},
        "usage": {},
    }

    _trim_to_budget(pack, 500)

    assert pack["constraints"]
    assert pack["evidence"] == []
    assert pack["token_used"] <= 500


def test_shadow_comparison_keeps_legacy_as_served_result() -> None:
    comparison = _context_shadow_comparison(
        {
            "constraints": [{"id": "shared"}, {"id": "legacy"}],
            "memories": [],
            "evidence": [],
            "artifacts": [],
        },
        {
            "context_run_id": "run-id",
            "token_used": 321,
            "constraints": [{"id": "shared"}, {"id": "compiler"}],
            "memories": [],
            "evidence": [],
            "artifacts": [],
        },
    )

    assert comparison["served_by"] == "legacy"
    assert comparison["compiler_context_run_id"] == "run-id"
    assert comparison["domains"]["constraints"] == {
        "legacy_count": 2,
        "compiler_count": 2,
        "overlap_count": 1,
        "jaccard": 0.3333,
        "compiler_only_ids": ["compiler"],
        "legacy_only_ids": ["legacy"],
    }


@pytest.mark.asyncio
async def test_required_artifact_embeddings_fail_the_batch() -> None:
    artifact = ProjectArtifact(
        id=uuid.uuid4(),
        user_id="user",
        project_id="EchoMe",
        logical_path="docs/architecture.md",
        kind="document",
        title="Architecture",
        content="Architecture content that requires a searchable embedding.",
        content_hash="a" * 64,
        size_bytes=58,
    )
    session = AsyncMock()

    with (
        patch("app.api.project_knowledge.get_embeddings", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _create_artifact_chunks(
            session,
            artifact,
            include_embeddings=True,
            require_embeddings=True,
        )

    assert exc_info.value.status_code == 503
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_artifact_embeddings_are_generated_in_small_batches() -> None:
    artifact = ProjectArtifact(
        id=uuid.uuid4(),
        user_id="user",
        project_id="EchoMe",
        logical_path="echome_mcp/server.py",
        kind="code",
        title="MCP server",
        content="patched below",
        content_hash="b" * 64,
        size_bytes=13,
    )
    raw_chunks = [
        {"content": f"chunk {index}", "locator": {"line_start": index + 1}}
        for index in range(10)
    ]
    generated = AsyncMock(
        side_effect=[
            [[float(index)] * 1024 for index in range(8)],
            [[float(index)] * 1024 for index in range(8, 10)],
        ]
    )
    session = MagicMock()
    session.flush = AsyncMock()

    with (
        patch("app.api.project_knowledge.split_artifact_content", return_value=raw_chunks),
        patch("app.api.project_knowledge.get_embeddings", new=generated),
    ):
        chunks = await _create_artifact_chunks(
            session,
            artifact,
            include_embeddings=True,
            require_embeddings=True,
        )

    assert generated.await_count == 2
    assert len(chunks) == 10
    assert all(chunk.embedding is not None for chunk in chunks)
