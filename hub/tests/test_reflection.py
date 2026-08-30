"""Tests for evidence-backed, freshness-gated project reflection."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.project_knowledge import (
    create_knowledge_view,
    prepare_knowledge_reflection,
    submit_knowledge_reflection,
)
from app.models.memory import Memory, Project
from app.models.project_knowledge import KnowledgeView
from app.schemas.project_knowledge import (
    KnowledgeViewCreate,
    ReflectionClaim,
    ReflectionPrepareRequest,
    ReflectionSubmitRequest,
)
from app.services.context_compiler import _view_is_fresh
from app.services.reflection import (
    ReflectionSourceChangedError,
    build_source_watermark,
    reflection_request_fingerprint,
    render_reflection_claims,
    validate_claim_sources,
    verify_source_watermark,
)


def _scalar_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _memory() -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(
        id=uuid.uuid4(),
        user_id="user",
        title="Current release",
        content="The current release is 1.7.1.",
        type="project",
        layer="L1",
        scope_global=False,
        scope_projects=["qzhqzh/EchoMe"],
        status="active",
        sleep_state="reviewed",
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_reflection_watermark_rejects_changed_source_content() -> None:
    memory = _memory()
    prepare_session = AsyncMock()
    prepare_session.execute = AsyncMock(
        side_effect=[_scalar_result([]), _scalar_result([memory])]
    )
    watermark = await build_source_watermark(
        prepare_session,
        user_id="user",
        project_id="qzhqzh/EchoMe",
        source_ids={"memory_ids": [memory.id]},
    )
    memory.content = "The current release changed after prepare."
    submit_session = AsyncMock()
    submit_session.execute = AsyncMock(
        side_effect=[_scalar_result([]), _scalar_result([memory])]
    )

    with pytest.raises(ReflectionSourceChangedError, match="changed after prepare"):
        await verify_source_watermark(
            submit_session,
            user_id="user",
            project_id="qzhqzh/EchoMe",
            source_watermark=watermark,
        )
    submitted_statement = submit_session.execute.await_args_list[-1].args[0]
    assert submitted_statement._for_update_arg is not None


def test_reflection_claim_must_cite_prepared_source() -> None:
    prepared_id = uuid.uuid4()
    claim = ReflectionClaim(
        statement="The API remains backward compatible.",
        confidence=0.9,
        evidence_refs=[
            {
                "target_type": "constraint",
                "target_id": uuid.uuid4(),
                "relation": "supports",
            }
        ],
    )

    with pytest.raises(ReflectionSourceChangedError, match="outside the prepared context"):
        validate_claim_sources(
            [claim],
            {
                "constraint_ids": [str(prepared_id)],
                "memory_ids": [],
                "artifact_ids": [],
                "event_ids": [],
            },
        )


def test_reflection_schema_rejects_claim_without_evidence() -> None:
    with pytest.raises(ValidationError):
        ReflectionClaim(
            statement="Unsupported claim",
            confidence=0.5,
            evidence_refs=[],
        )


def test_reflection_submit_rejects_unbound_content_and_client_producer() -> None:
    source_id = uuid.uuid4()
    payload = {
        "project_id": "qzhqzh/EchoMe",
        "query": "Architecture",
        "claims": [
            {
                "statement": "Supported claim",
                "confidence": 0.9,
                "evidence_refs": [{"target_type": "memory", "target_id": source_id}],
            }
        ],
        "source_watermark": {},
        "idempotency_key": "reflect-1",
    }

    with pytest.raises(ValidationError):
        ReflectionSubmitRequest(**payload, content="Uncited narrative")
    with pytest.raises(ValidationError):
        ReflectionSubmitRequest(**payload, producer="system")


def test_reflection_content_is_rendered_from_cited_claims() -> None:
    source_id = uuid.uuid4()
    claim = ReflectionClaim(
        statement="The gateway is the stable entry point.",
        confidence=0.875,
        evidence_refs=[{"target_type": "constraint", "target_id": source_id}],
    )

    rendered = render_reflection_claims([claim])

    assert "The gateway is the stable entry point." in rendered
    assert "Confidence: 0.875" in rendered
    assert f"constraint:{source_id}" in rendered


def test_legacy_derived_view_retains_artifact_id_freshness_compatibility() -> None:
    legacy = KnowledgeView(
        id=uuid.uuid4(),
        user_id="user",
        project_id="qzhqzh/EchoMe",
        kind="summary",
        content="Legacy generated summary",
        source_watermark={"artifact_ids": []},
        refresh_mode="derived",
        status="current",
    )

    assert _view_is_fresh(legacy, set(), {}) is True

    legacy.source_watermark = {"artifact_ids": [str(uuid.uuid4())]}
    assert _view_is_fresh(legacy, set(), {}) is False


@pytest.mark.asyncio
async def test_legacy_derived_view_creation_remains_backward_compatible() -> None:
    project = Project(id="qzhqzh/EchoMe", user_id="user", name="EchoMe")
    session = MagicMock()
    session.add = MagicMock()

    async def flush() -> None:
        view = session.add.call_args.args[0]
        view.id = uuid.uuid4()
        view.status = "current"
        view.schema_version = 1
        view.created_at = datetime.now(timezone.utc)

    session.flush = AsyncMock(side_effect=flush)
    body = KnowledgeViewCreate(
        project_id=project.id,
        kind="summary",
        content="Legacy client-generated summary",
        source_watermark={"artifact_ids": []},
        refresh_mode="derived",
        producer="legacy_client",
    )

    with (
        patch(
            "app.api.project_knowledge._require_project",
            new=AsyncMock(return_value=project),
        ),
        patch(
            "app.api.project_knowledge._validate_source_refs",
            new=AsyncMock(),
        ),
    ):
        result = await create_knowledge_view(body, session=session, user_id="user")

    assert result["refresh_mode"] == "derived"
    assert result["producer"] == "legacy_client"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reflection_prepare_is_read_only() -> None:
    project = Project(id="qzhqzh/EchoMe", user_id="user", name="EchoMe")
    context = {
        "project": {"id": project.id, "name": project.name},
        "constraints": [],
        "memories": [],
        "artifacts": [],
        "evidence": [],
    }
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result([]),
            _scalar_result([]),
        ]
    )
    session.add = MagicMock()
    watermark = {
        "schema_version": "echome.reflect.v1",
        "project_id": project.id,
        "memory_ids": [],
        "constraint_ids": [],
        "artifact_ids": [],
        "event_ids": [],
        "source_fingerprint": "0" * 64,
        "source_versions": {},
        "source_count": 0,
    }
    with (
        patch(
            "app.api.project_knowledge._require_project",
            new=AsyncMock(return_value=project),
        ),
        patch(
            "app.api.project_knowledge.compile_project_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "app.api.project_knowledge.build_source_watermark",
            new=AsyncMock(return_value=watermark),
        ),
    ):
        result = await prepare_knowledge_reflection(
            ReflectionPrepareRequest(project_id=project.id, query="Summarize architecture"),
            session=session,
            user_id="user",
        )

    assert result["read_only"] is True
    assert result["source_watermark"] == {
        key: value for key, value in watermark.items() if key != "source_versions"
    }
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_reflection_prepare_rejects_mixed_context_and_watermark_snapshots() -> None:
    project = Project(id="qzhqzh/EchoMe", user_id="user", name="EchoMe")
    source_id = uuid.uuid4()
    source_key = f"memory:{source_id}"
    context = {
        "project": {"id": project.id, "name": project.name},
        "constraints": [],
        "memories": [{"id": str(source_id)}],
        "artifacts": [],
        "evidence": [],
        "_source_versions": {source_key: "old-version"},
    }
    watermark = {
        "schema_version": "echome.reflect.v1",
        "project_id": project.id,
        "memory_ids": [str(source_id)],
        "constraint_ids": [],
        "artifact_ids": [],
        "event_ids": [],
        "source_fingerprint": "0" * 64,
        "source_versions": {source_key: "new-version"},
        "source_count": 1,
    }
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))

    with (
        patch(
            "app.api.project_knowledge._require_project",
            new=AsyncMock(return_value=project),
        ),
        patch(
            "app.api.project_knowledge.compile_project_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "app.api.project_knowledge.build_source_watermark",
            new=AsyncMock(return_value=watermark),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await prepare_knowledge_reflection(
            ReflectionPrepareRequest(project_id=project.id, query="Architecture"),
            session=session,
            user_id="user",
        )

    assert exc_info.value.status_code == 409
    assert "changed during prepare" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_reflection_submit_does_not_write_after_fingerprint_conflict() -> None:
    project = Project(id="qzhqzh/EchoMe", user_id="user", name="EchoMe")
    source_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.add = MagicMock()
    body = ReflectionSubmitRequest(
        project_id=project.id,
        query="Summarize architecture",
        idempotency_key="reflect-conflict-1",
        claims=[
            {
                "statement": "Claim",
                "confidence": 0.8,
                "evidence_refs": [
                    {
                        "target_type": "memory",
                        "target_id": source_id,
                    }
                ],
            }
        ],
        source_watermark={
            "schema_version": "echome.reflect.v1",
            "project_id": project.id,
            "memory_ids": [str(source_id)],
            "constraint_ids": [],
            "artifact_ids": [],
            "event_ids": [],
            "source_fingerprint": "0" * 64,
        },
    )
    with (
        patch(
            "app.api.project_knowledge._require_project",
            new=AsyncMock(return_value=project),
        ),
        patch(
            "app.api.project_knowledge.verify_source_watermark",
            new=AsyncMock(side_effect=ReflectionSourceChangedError("sources changed")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await submit_knowledge_reflection(body, session=session, user_id="user")

    assert exc_info.value.status_code == 409
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_reflection_submit_replays_same_idempotent_result() -> None:
    project = Project(id="qzhqzh/EchoMe", user_id="user", name="EchoMe")
    source_id = uuid.uuid4()
    body = ReflectionSubmitRequest(
        project_id=project.id,
        query="Summarize architecture",
        idempotency_key="reflect-replay-1",
        claims=[
            {
                "statement": "The gateway is stable.",
                "confidence": 0.9,
                "evidence_refs": [{"target_type": "memory", "target_id": source_id}],
            }
        ],
        source_watermark={
            "schema_version": "echome.reflect.v1",
            "project_id": project.id,
            "memory_ids": [str(source_id)],
            "constraint_ids": [],
            "artifact_ids": [],
            "event_ids": [],
            "source_fingerprint": "0" * 64,
        },
    )
    request_fingerprint = reflection_request_fingerprint(
        project_id=project.id,
        kind=body.kind,
        query=body.query,
        claims=body.claims,
        source_fingerprint=body.source_watermark["source_fingerprint"],
        supersedes_id=None,
    )
    existing = KnowledgeView(
        id=uuid.uuid4(),
        user_id="user",
        project_id=project.id,
        kind=body.kind,
        query=body.query,
        content=render_reflection_claims(body.claims),
        source_watermark={
            "idempotency_key": body.idempotency_key,
            "request_fingerprint": request_fingerprint,
            "claims": [item.model_dump(mode="json") for item in body.claims],
        },
        refresh_mode="derived",
        producer="client_ai",
        created_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=existing)
    session.add = MagicMock()
    verify = AsyncMock()

    with (
        patch(
            "app.api.project_knowledge._require_project",
            new=AsyncMock(return_value=project),
        ),
        patch("app.api.project_knowledge.verify_source_watermark", new=verify),
    ):
        result = await submit_knowledge_reflection(body, session=session, user_id="user")

    assert result["idempotent_replay"] is True
    assert result["id"] == str(existing.id)
    verify.assert_not_awaited()
    session.add.assert_not_called()
