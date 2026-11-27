"""Automatic discovery remains scoped, read-only, bounded, and opt-in."""

import asyncio
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.api.context_runtime import get_context_discovery, router
from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory
from app.schemas.context_runtime import ContextDiscoveryRequest
from app.services.context_discovery import build_discovery
from app.services.context_output import measure_output
from app.services.memory_retrieval import MemoryRetrievalResult, RankedMemory, retrieve_memories

OWNER = "discovery-owner"


def _memory(title: str, content: str = "An existing decision.") -> Memory:
    return Memory(
        id=uuid.uuid4(), user_id=OWNER, title=title, content=content,
        type="context", layer="L1", status="active", priority=5,
        tags=[], scope_global=True, scope_projects=[], scope_exclude=[],
        updated_at=datetime.now(timezone.utc),
    )


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.begin_nested = MagicMock(return_value=AsyncMock())
    session.scalar.return_value = 0
    session.is_active = True
    return session


def _no_writes(session: AsyncMock) -> None:
    session.add.assert_not_called()
    session.add_all.assert_not_called()
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.delete.assert_not_awaited()


def _stub_candidates(monkeypatch: pytest.MonkeyPatch) -> tuple[Memory, AsyncMock, AsyncMock]:
    memory = _memory("Customer database migration", "Preserve existing customer records.")
    retrieval = AsyncMock(return_value=MemoryRetrievalResult(
        items=[RankedMemory(memory, 0.8)], total_candidates=1,
        trace={"vector_available": True},
    ))
    policy = AsyncMock()
    monkeypatch.setattr("app.services.context_discovery.retrieve_memories", retrieval)
    monkeypatch.setattr("app.services.context_discovery.apply_context_policy", policy)
    return memory, retrieval, policy


@pytest.mark.asyncio
async def test_registered_project_uses_owner_scopes_without_compiling_or_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory, retrieval, policy = _stub_candidates(monkeypatch)
    project = SimpleNamespace(id="owner/okbox", name="OKBOX")
    resolution = SimpleNamespace(project=project)
    resolve = AsyncMock(side_effect=[HTTPException(404), resolution])
    scopes = AsyncMock(return_value=[project.id, "legacy-okb"])
    monkeypatch.setattr("app.services.context_discovery.resolve_project", resolve)
    monkeypatch.setattr("app.services.context_discovery.project_scope_ids", scopes)
    compiler = AsyncMock(side_effect=AssertionError("Discovery must not compile full context"))
    preflight = AsyncMock(side_effect=AssertionError("Discovery must not run preflight"))
    monkeypatch.setattr("app.api.context_runtime.compile_project_context", compiler)
    monkeypatch.setattr("app.api.context_runtime.project_preflight", preflight)
    knowledge = AsyncMock(return_value=[])
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", knowledge)
    session = _session()
    body = ContextDiscoveryRequest(
        task="Upgrade OKBOX while preserving the customer database",
        project_hint="/new/worktree", project_hints=["owner/okbox"],
    )

    output = await get_context_discovery(body, session, OWNER)

    assert output["scope"] == "project"
    assert output["project"] == {"id": project.id, "name": project.name}
    assert output["project_resolution"]["status"] == "resolved"
    assert output["memory_index"][0]["id"] == str(memory.id)
    assert output["memory_index"][0]["needs_expansion"] is True
    assert "content" not in output["memory_index"][0]
    assert output["project_reference"]["read"]["arguments"]["project_hint"] == project.id
    assert output["runtime"]["read_only"] is True
    assert output["runtime"]["record_run"] is False
    assert "context_run_id" not in output and "completion_contract" not in output
    assert all(call.args[1] == OWNER for call in resolve.await_args_list)
    scopes.assert_awaited_once_with(session, OWNER, project.id)
    assert retrieval.await_args.kwargs["user_id"] == OWNER
    assert retrieval.await_args.kwargs["project_scope_ids"] == [project.id, "legacy-okb"]
    assert retrieval.await_args.kwargs["global_only"] is False
    assert retrieval.await_args.kwargs["discovery"] is True
    assert knowledge.await_args.kwargs["user_id"] == OWNER
    assert knowledge.await_args.kwargs["project_id"] == project.id
    assert knowledge.await_args.kwargs["discovery"] is True
    assert policy.await_args.kwargs["persist_assessments"] is False
    assert policy.await_args.kwargs["requested_mode"] == "shadow"
    assert policy.await_args.kwargs["enforce_enabled"] is False
    compiler.assert_not_awaited()
    preflight.assert_not_awaited()
    _no_writes(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_hints", "unknown", "ambiguous_alias", "conflicting_hints"])
async def test_unresolved_identity_falls_back_to_personal_without_guessing_or_registration(
    monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    _, retrieval, _ = _stub_candidates(monkeypatch)
    resolves: list[Any] = []
    hints: list[str] = []
    if case == "unknown":
        hints, resolves = ["/unregistered"], [HTTPException(404)]
    elif case == "ambiguous_alias":
        hints, resolves = ["shared-name"], [HTTPException(409)]
    elif case == "conflicting_hints":
        hints = ["project-a", "project-b"]
        resolves = [SimpleNamespace(project=SimpleNamespace(id=value)) for value in hints]
    resolve = AsyncMock(side_effect=resolves)
    scopes = AsyncMock(side_effect=AssertionError("No project scope without a unique identity"))
    monkeypatch.setattr("app.services.context_discovery.resolve_project", resolve)
    monkeypatch.setattr("app.services.context_discovery.project_scope_ids", scopes)
    session = _session()

    output = await build_discovery(
        session, ContextDiscoveryRequest(task="Find prior deployment decisions", project_hints=hints),
        OWNER,
    )

    assert output["scope"] == "personal"
    assert output["project"] is None and "project_reference" not in output
    expected = "ambiguous" if case in {"ambiguous_alias", "conflicting_hints"} else "not_found"
    assert output["project_resolution"]["status"] == expected
    assert output["project_resolution"]["requires_confirmation"] is False
    assert retrieval.await_args.kwargs["global_only"] is True
    assert retrieval.await_args.kwargs["project_scope_ids"] is None
    assert retrieval.await_args.kwargs["user_id"] == OWNER
    scopes.assert_not_awaited()
    _no_writes(session)


@pytest.mark.asyncio
async def test_identity_authorization_errors_are_not_disguised_as_missing_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, retrieval, _ = _stub_candidates(monkeypatch)
    monkeypatch.setattr(
        "app.services.context_discovery.resolve_project",
        AsyncMock(side_effect=HTTPException(403, "Forbidden")),
    )

    with pytest.raises(HTTPException) as error:
        await build_discovery(
            _session(), ContextDiscoveryRequest(task="Find decisions", project_hint="private"), OWNER,
        )

    assert error.value.status_code == 403
    retrieval.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_retrieval_sql_enforces_owner_global_project_and_exclusion_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.memory_retrieval.get_embedding", AsyncMock(return_value=None))
    count_result, candidate_result = MagicMock(), MagicMock()
    count_result.scalar_one.return_value = 0
    candidate_result.scalars.return_value.all.return_value = []
    session = _session()
    session.execute.side_effect = [count_result, candidate_result]

    await retrieve_memories(
        session, user_id=OWNER, query="OKBOX customer migration", limit=3,
        project_scope_ids=["owner/okbox", "legacy-okb"], discovery=True,
    )

    # Both candidate counting and the actual retrieval must preserve the same
    # owner and exclusion boundary; aliases cannot bypass an explicit exclusion.
    for call in session.execute.await_args_list:
        compiled = call.args[0].compile(dialect=postgresql.dialect())
        sql = str(compiled)
        values = list(compiled.params.values())
        assert "memories.user_id =" in sql and OWNER in values
        assert "memories.scope_global IS true OR" in sql
        assert "memories.scope_projects @>" in sql
        assert re.search(r"NOT \(+memories.scope_exclude @>", sql)
        assert values.count(["owner/okbox"]) == 2
        assert values.count(["legacy-okb"]) == 2
    _no_writes(session)


@pytest.mark.asyncio
async def test_optional_knowledge_failure_keeps_the_memory_index_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory, _, _ = _stub_candidates(monkeypatch)
    monkeypatch.setattr("app.services.context_discovery.resolve_project", AsyncMock())
    monkeypatch.setattr(
        "app.api.context_runtime.discover_knowledge_refs",
        AsyncMock(side_effect=SQLAlchemyError("Knowledge unavailable")),
    )
    session = _session()

    output = await get_context_discovery(
        ContextDiscoveryRequest(task="Find prior migration decisions"), session, OWNER,
    )

    assert output["memory_index"][0]["id"] == str(memory.id)
    assert output["knowledge_refs"] == []
    assert output["runtime"]["knowledge_lookup"] == "unavailable"
    assert any("unavailable" in warning for warning in output["unknowns"])
    _no_writes(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [1000, 1600, 3000])
async def test_discovery_never_exceeds_the_whole_response_budget(
    monkeypatch: pytest.MonkeyPatch, budget: int,
) -> None:
    _stub_candidates(monkeypatch)
    monkeypatch.setattr("app.services.context_discovery.resolve_project", AsyncMock())
    monkeypatch.setattr(
        "app.api.context_runtime.discover_knowledge_refs",
        AsyncMock(return_value=[{
            "id": "large-reference", "title": "中文知识索引" * 1000,
            "needs_expansion": True,
        }]),
    )

    output = await get_context_discovery(
        ContextDiscoveryRequest(task="Find prior migration decisions", max_output_tokens=budget),
        _session(), OWNER,
    )

    assert measure_output(output) <= budget
    if "error" in output:
        assert output["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    else:
        assert output["output_usage"]["tokens_upper_bound"] == measure_output(output)
        assert output["knowledge_refs"] == []
        assert output["omitted_counts"]["knowledge_refs"] == 1
        assert "complete context" in output["notice"]


@pytest.mark.asyncio
async def test_discovery_reports_budget_error_when_project_identity_envelope_cannot_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_candidates(monkeypatch)
    project = SimpleNamespace(id="owner/project", name="Long project name " * 100)
    monkeypatch.setattr(
        "app.services.context_discovery.resolve_project",
        AsyncMock(return_value=SimpleNamespace(project=project)),
    )
    monkeypatch.setattr(
        "app.services.context_discovery.project_scope_ids", AsyncMock(return_value=[project.id]),
    )
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", AsyncMock(return_value=[]))

    output = await get_context_discovery(
        ContextDiscoveryRequest(task="Find decisions", project_hint=project.id, max_output_tokens=1000),
        _session(), OWNER,
    )

    assert output["schema_version"] == "echome.error.v1"
    assert output["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    assert measure_output(output) <= 1000


@pytest.mark.asyncio
async def test_discovery_denoising_does_not_narrow_explicit_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    useful = _memory("外显子总数", "保存每个转录本的外显子数量。")
    unrelated = _memory("记录", "保存应用操作日志。")
    monkeypatch.setattr("app.services.memory_retrieval.get_embedding", AsyncMock(return_value=None))
    results = {}
    for discovery in (False, True):
        count_result, candidate_result = MagicMock(), MagicMock()
        count_result.scalar_one.return_value = 2
        candidate_result.scalars.return_value.all.return_value = [useful, unrelated]
        session = _session()
        session.execute.side_effect = [count_result, candidate_result]
        results[discovery] = await retrieve_memories(
            session, user_id=OWNER, query="这个项目是否记录外显子总数", limit=3,
            discovery=discovery,
        )

    assert {item.memory.id for item in results[False].items} == {useful.id, unrelated.id}
    assert {item.memory.id for item in results[True].items} == {useful.id}


@pytest.mark.asyncio
async def test_discovery_api_authentication_and_validation_do_not_touch_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = AsyncMock(side_effect=AssertionError("Invalid requests must not retrieve"))
    monkeypatch.setattr("app.api.context_runtime.build_discovery", builder)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_session() -> AsyncMock:
        return _session()

    async def override_user() -> str:
        return OWNER

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await asyncio.wait_for(
            client.post("/api/v1/context/discovery", json={"task": "history"}), timeout=2,
        )
        assert unauthorized.status_code in {401, 403}
        app.dependency_overrides[verify_token] = override_user
        invalid = await asyncio.wait_for(
            client.post("/api/v1/context/discovery", json={"task": "", "limit": 100}), timeout=2,
        )
        assert invalid.status_code == 422
        assert invalid.json()["schema_version"] == "echome.error.v1"
    builder.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_concern_warning_survives_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _ = _stub_candidates(monkeypatch)

    async def annotate(*args: Any, **kwargs: Any) -> None:
        kwargs['context']['memories'][0]['warning'] = {
            'code': 'reported_memory_concern',
            'message': 'Feedback is not verified; prefer current evidence.',
        }

    monkeypatch.setattr('app.services.context_discovery.apply_context_policy', annotate)
    result = await build_discovery(_session(), ContextDiscoveryRequest(task='a useful task'), OWNER)
    assert result['memory_index'][0]['warning']['code'] == 'reported_memory_concern'
