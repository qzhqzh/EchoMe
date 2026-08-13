"""Unified context runtime contract tests."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api.context_runtime import (
    _answerability,
    _personal_context,
    get_unified_context,
    router,
    runtime_health,
)
from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory
from app.schemas.context_runtime import UnifiedContextRequest


def test_answerability_does_not_hide_conflicts() -> None:
    assert _answerability({"conflicts": [{"id": "conflict"}], "unknowns": []}) == "conflicted"
    assert _answerability({"conflicts": [], "unknowns": ["missing"]}) == "insufficient_evidence"


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
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()

    context = await _personal_context(
        session,
        UnifiedContextRequest(task="Git workflow", client="test"),
        "user",
        "request-id",
    )

    assert context["memories"][0]["id"] == str(memory.id)
    run = session.add.call_args.args[0]
    assert run.project_id is None
    assert run.route == "personal"
    assert run.selected == {"memories": [str(memory.id)]}


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
