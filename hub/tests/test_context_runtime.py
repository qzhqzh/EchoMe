"""Unified context runtime contract tests."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api.context_runtime import (
    _answerability,
    _build_unified_context,
    _personal_context,
    get_unified_context,
    router,
    runtime_health,
)
from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory
from app.schemas.context_runtime import UnifiedContextRequest
from app.services.project_identity import ProjectDiscovery


def test_answerability_does_not_hide_conflicts() -> None:
    assert _answerability({"conflicts": [{"id": "conflict"}], "unknowns": []}) == "conflicted"
    assert _answerability({"conflicts": [], "unknowns": ["missing"]}) == "insufficient_evidence"


def test_explicit_project_mode_accepts_multiple_identity_hints() -> None:
    body = UnifiedContextRequest(
        task="inspect project",
        project_hints=["git@example.com:owner/repo.git", "/srv/repo"],
        mode="project",
    )

    assert body.project_hint is None
    assert len(body.project_hints) == 2


@pytest.mark.asyncio
async def test_personal_context_records_actual_selected_memories() -> None:
    memory = Memory(
        id=uuid.uuid4(),
        user_id="user",
        title="Git workflow",
        content="Use pull requests for Git changes.",
        type="method",
        layer="L1",
        scope_global=True,
        priority=8,
        tags=["git"],
        status="active",
        updated_at=datetime.now(timezone.utc),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [memory]
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, result])
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def apply_policy(*_args, **kwargs):
        kwargs["context"]["memories"][0]["reliability"] = {"reason_codes": ["diagnostic" * 2000]}
        kwargs["context"]["context_policy"] = {"effective_mode": "shadow"}
        return kwargs["context"]

    with (
        patch("app.services.memory_retrieval.get_embedding", return_value=None),
        patch("app.api.context_runtime.apply_context_policy", side_effect=apply_policy),
    ):
        context = await _personal_context(
            session,
            UnifiedContextRequest(task="Git workflow", client="test"),
            "user",
            "request-id",
        )

    assert context["memories"][0]["id"] == str(memory.id)
    assert context["retrieval_trace"]["strategy"] == "hybrid_memory"
    assert context["retrieval_trace"]["selected_count"] == 1
    assert context["token_used"] <= context["token_budget"]
    assert context["context_policy"]["diagnostic_token_overhead"] > 0
    assert context["completion_contract"]["report_outcome"] is True
    assert context["completion_contract"]["context_run_id"] == context["context_run_id"]
    assert context["completion_contract"]["idempotency_key"].endswith(":completion")
    run = session.add.call_args.args[0]
    assert run.project_id is None
    assert run.route == "personal"
    assert run.selected == {"memories": [str(memory.id)]}


@pytest.mark.asyncio
async def test_personal_context_trace_reflects_token_budget_truncation() -> None:
    memory = Memory(
        id=uuid.uuid4(),
        user_id="user",
        title="Large workflow",
        content="workflow " * 2000,
        type="method",
        layer="L1",
        scope_global=True,
        priority=8,
        tags=["workflow"],
        status="active",
        updated_at=datetime.now(timezone.utc),
    )
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    candidate_result = MagicMock()
    candidate_result.scalars.return_value.all.return_value = [memory]
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, candidate_result])
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def apply_policy(*_args, **kwargs):
        kwargs["context"]["context_policy"] = {"effective_mode": "shadow"}
        return kwargs["context"]

    with (
        patch("app.services.memory_retrieval.get_embedding", return_value=None),
        patch("app.api.context_runtime.apply_context_policy", side_effect=apply_policy),
    ):
        context = await _personal_context(
            session,
            UnifiedContextRequest(
                task="workflow",
                token_budget=256,
                record_run=False,
            ),
            "user",
            "request-id",
        )

    assert context["memories"] == []
    assert context["retrieval_trace"]["selected_count"] == 0


@pytest.mark.asyncio
async def test_failed_context_is_sent_to_independent_audit(monkeypatch) -> None:
    body = UnifiedContextRequest(task="unknown project", project_hint="missing")
    failure = RuntimeError("compiler failed")
    record = AsyncMock()

    async def fail_build(*args):
        args[3]["project_id"] = "canonical"
        raise failure

    monkeypatch.setattr("app.api.context_runtime._build_unified_context", fail_build)
    monkeypatch.setattr("app.api.context_runtime._record_failed_context", record)

    session = AsyncMock()
    response = await get_unified_context(body, session, "user")

    assert response.status_code == 500
    assert json.loads(response.body)["error"]["code"] == "CONTEXT_RUNTIME_FAILED"
    session.rollback.assert_awaited_once()
    assert record.await_args.args[1] == "user"
    assert record.await_args.args[3] == "project"
    assert record.await_args.args[4] is failure
    assert record.await_args.args[5] == "canonical"


@pytest.mark.asyncio
async def test_context_http_errors_use_runtime_contract(monkeypatch) -> None:
    body = UnifiedContextRequest(task="unknown project", project_hint="missing")

    async def fail_build(*_args):
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr("app.api.context_runtime._build_unified_context", fail_build)
    monkeypatch.setattr("app.api.context_runtime._record_failed_context", AsyncMock())
    response = await get_unified_context(body, AsyncMock(), "user")
    payload = json.loads(response.body)

    assert response.status_code == 404
    assert payload["schema_version"] == "echome.error.v1"
    assert payload["error"]["code"] == "PROJECT_NOT_FOUND"
    assert payload["error"]["request_id"]


@pytest.mark.asyncio
async def test_unresolved_project_returns_non_terminal_recovery_envelope(monkeypatch) -> None:
    body = UnifiedContextRequest(
        task="inspect new project",
        project_hints=["git@example.com:owner/new-repo.git", "/srv/new-repo"],
        mode="project",
    )
    discovery = ProjectDiscovery(
        status="not_found",
        hints=tuple(body.project_hints),
        candidates=(),
    )
    monkeypatch.setattr(
        "app.api.context_runtime.discover_projects",
        AsyncMock(return_value=discovery),
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    payload = await _build_unified_context(body, session, "user", {"project_id": None})

    assert payload["scope"] == "project_resolution"
    assert payload["answerability"] == "insufficient_evidence"
    assert payload["project_resolution"]["status"] == "not_found"
    assert payload["project_resolution"]["create_proposal"]["project_id"] == "owner/new-repo"
    assert payload["runtime"]["resolution_required"] is True
    assert "completion_contract" not in payload
    run = session.add.call_args.args[0]
    assert run.status == "failed"
    assert run.error_code == "PROJECT_RESOLUTION_REQUIRED"


@pytest.mark.asyncio
async def test_context_asgi_auth_and_validation_errors_use_runtime_contract() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_session():
        return AsyncMock()

    async def override_user():
        return "user"

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await asyncio.wait_for(
            client.post("/api/v1/context", json={"task": "test"}), timeout=2
        )
        assert unauthorized.status_code in {401, 403}
        assert unauthorized.json()["schema_version"] == "echome.error.v1"

        app.dependency_overrides[verify_token] = override_user
        invalid = await asyncio.wait_for(
            client.post("/api/v1/context", json={"task": ""}), timeout=2
        )

    assert invalid.status_code == 422
    assert invalid.json()["schema_version"] == "echome.error.v1"
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_health_rolls_back_failed_database_probe(monkeypatch) -> None:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("database unavailable"))

    class Response:
        is_success = True

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return Response()

    monkeypatch.setattr("app.api.context_runtime.httpx.AsyncClient", lambda **_kwargs: Client())

    result = await runtime_health(session, "user")

    assert result["components"]["database"] == "unavailable"
    session.rollback.assert_awaited_once()
