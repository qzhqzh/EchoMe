"""Optional knowledge discovery preserves scope, budgets, and failure boundaries."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.api.context_runtime import _append_knowledge_refs, get_unified_context
from app.schemas.context_runtime import UnifiedContextRequest
from app.services.context_output import content_tokens, context_output, measure_output


def reference(source: str = "knowledge", record_id: str = "knowledge-id") -> dict:
    return {
        "source": source,
        "id": record_id,
        "kind": "entity" if source == "knowledge" else "scene_entry",
        "revision": 2,
        "title": "Deployment approach",
        "snippet": "This candidate may describe the relevant deployment history.",
        "needs_expansion": True,
        "review_state": "unchecked",
        "read": {"tool": "echome_knowledge_read", "arguments": {"action": "get", "record_id": record_id}},
    }


def mock_session():
    session = AsyncMock()
    session.is_active = True
    session.scalar.return_value = "0"
    session.begin_nested = MagicMock(return_value=AsyncMock())
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["personal", "project"])
async def test_discovery_receives_resolved_scope_and_does_not_promote_refs_to_source(monkeypatch, scope):
    refs = [reference(), reference("scene", "scene-entry-id")]
    discover = AsyncMock(return_value=refs)
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", discover)
    context = {
        "scope": scope,
        "project": {"id": "canonical"} if scope == "project" else None,
        "memories": [],
        "answerability": "insufficient_evidence",
    }
    session = mock_session()

    await _append_knowledge_refs(context, UnifiedContextRequest(task="deployment"), session, "user")

    assert discover.await_args.kwargs == {
        "user_id": "user", "query": "deployment", "project_id": "canonical" if scope == "project" else None,
        "limit": 4,
    }
    assert context["knowledge_refs"] == refs
    assert context["memories"] == []
    assert context["answerability"] == "insufficient_evidence"
    assert content_tokens(context) == 0
    assert context["retrieval_trace"]["knowledge_lookup"]["candidate_count"] == 2
    session.begin_nested.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unresolved", "temporal", "as_of", "valid_at"])
async def test_discovery_does_not_mix_current_knowledge_into_unresolved_or_historical_context(monkeypatch, case):
    discover = AsyncMock()
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", discover)
    params = {"task": "history"}
    if case == "temporal":
        params.update(mode="temporal", project_hint="canonical")
    elif case in {"as_of", "valid_at"}:
        params[case] = datetime(2025, 1, 1, tzinfo=timezone.utc)
    context = {"scope": "project_resolution" if case == "unresolved" else "personal"}

    await _append_knowledge_refs(context, UnifiedContextRequest(**params), mock_session(), "user")

    discover.assert_not_awaited()
    assert "knowledge_refs" not in context
    if case != "unresolved":
        assert context["retrieval_trace"]["knowledge_lookup"]["reason"] == "historical_request"


@pytest.mark.asyncio
async def test_database_failure_rolls_back_savepoint_and_preserves_original_pack(monkeypatch):
    monkeypatch.setattr(
        "app.api.context_runtime.discover_knowledge_refs",
        AsyncMock(side_effect=SQLAlchemyError("private database details")),
    )
    context = {"scope": "personal", "memories": [{"id": "memory", "content": "Concise replies."}], "unknowns": []}
    original_memories = deepcopy(context["memories"])
    session = mock_session()

    await _append_knowledge_refs(context, UnifiedContextRequest(task="deployment"), session, "user")

    transaction = session.begin_nested.return_value
    assert transaction.__aexit__.await_args.args[0] is SQLAlchemyError
    assert context["memories"] == original_memories
    assert "knowledge_refs" not in context
    assert context["answerability"] == "partial"
    assert context["retrieval_trace"]["knowledge_lookup"]["reason"] == "database_error"
    assert "private database details" not in str(context)
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_statement_timeout_is_reported_as_optional_lookup_timeout(monkeypatch):
    cancelled = Exception("statement timeout")
    cancelled.sqlstate = "57014"
    monkeypatch.setattr(
        "app.api.context_runtime.discover_knowledge_refs",
        AsyncMock(side_effect=DBAPIError(None, None, cancelled)),
    )
    context = {"scope": "personal", "memories": [], "unknowns": []}

    await _append_knowledge_refs(context, UnifiedContextRequest(task="deployment"), mock_session(), "user")

    assert context["retrieval_trace"]["knowledge_lookup"]["reason"] == "timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    ValueError("bad projection"),
    TypeError("invalid mock"),
    DBAPIError(None, None, Exception("connection lost"), connection_invalidated=True),
])
async def test_programming_errors_are_not_disguised_as_optional_lookup_failures(monkeypatch, error):
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", AsyncMock(side_effect=error))

    with pytest.raises(type(error)):
        await _append_knowledge_refs({"scope": "personal"}, UnifiedContextRequest(task="deployment"), mock_session(), "user")


@pytest.mark.asyncio
async def test_failed_outer_transaction_is_not_claimed_as_successful_fallback(monkeypatch):
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", AsyncMock(side_effect=SQLAlchemyError()))
    session = mock_session()
    session.is_active = False

    with pytest.raises(SQLAlchemyError):
        await _append_knowledge_refs({"scope": "personal"}, UnifiedContextRequest(task="deployment"), session, "user")


def test_knowledge_refs_use_optional_budget_and_do_not_displace_complete_rules():
    rule = {"id": "rule", "type": "guardrail", "content": "Preserve user data."}
    oversized = reference(record_id="large")
    oversized["snippet"] *= 1000
    source = {"scope": "personal", "memories": [rule], "knowledge_refs": [oversized, reference()], "answerability": "supported"}

    output = context_output(source, mode="compact", limit=1300)

    assert output["memories"] == [rule]
    assert [item["id"] for item in output["knowledge_refs"]] == ["knowledge-id"]
    assert output["omitted_counts"] == {"knowledge_refs": 1}
    assert output["delivered_content_tokens"] == content_tokens({"memories": [rule]})
    assert output["knowledge_refs_tokens"] > 0
    assert measure_output(output) <= 1300


@pytest.mark.asyncio
async def test_runtime_records_candidate_and_delivered_reference_ids_separately(monkeypatch):
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    context = {
        "scope": "personal", "memories": [], "unknowns": [],
        "context_run_id": run_id, "answerability": "insufficient_evidence",
    }
    huge = reference(record_id="large")
    huge["snippet"] *= 1000
    monkeypatch.setattr("app.api.context_runtime._build_unified_context", AsyncMock(return_value=context))
    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", AsyncMock(return_value=[huge, reference("scene", "small")]))
    session = mock_session()
    run = SimpleNamespace(trace={}, selected={"memories": []}, status="completed")
    session.get.return_value = run

    output = await get_unified_context(
        UnifiedContextRequest(task="deployment", output_mode="compact", max_output_tokens=1400), session, "user",
    )

    assert run.trace["compiled_knowledge_refs"] == [{"source": "knowledge", "id": "large", "revision": 2}, {"source": "scene", "id": "small", "revision": 2}]
    assert run.trace["delivered_knowledge_refs"] == [{"source": "scene", "id": "small", "revision": 2}]
    assert run.trace["compiled_content_tokens"] == run.trace["delivered_content_tokens"] == 0
    assert run.trace["knowledge_refs_tokens"] == output["knowledge_refs_tokens"] > 0
    assert run.trace["knowledge_lookup"]["candidate_count"] == 2
    assert run.selected == {"memories": []}
