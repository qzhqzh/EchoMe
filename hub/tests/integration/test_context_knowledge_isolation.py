"""Real asyncpg failures must not discard the surrounding context run."""

import pytest
from sqlalchemy import text

from app.api.context_runtime import _append_knowledge_refs
from app.models.project_knowledge import ContextRun
from app.schemas.context_runtime import UnifiedContextRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "statement_error"])
async def test_optional_lookup_preserves_outer_transaction(
    database, test_user_id, monkeypatch, failure,
):
    async def fail_lookup(session, **_kwargs):
        statement = "SELECT pg_sleep(0.1)" if failure == "timeout" else "SELECT 1 / 0"
        await session.execute(text(statement))
        return []

    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", fail_lookup)
    monkeypatch.setattr("app.api.context_runtime.KNOWLEDGE_STATEMENT_TIMEOUT_MS", 10)
    context = {
        "scope": "personal",
        "memories": [{"id": "existing", "content": "Use current evidence."}],
        "unknowns": [],
    }
    async with database() as session:
        run = ContextRun(
            user_id=test_user_id,
            query="deployment context",
            mode="personal",
            token_budget=1000,
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
        previous_timeout = await session.scalar(text("SHOW statement_timeout"))

        await _append_knowledge_refs(
            context, UnifiedContextRequest(task="deployment"), session, test_user_id,
        )

        assert context["retrieval_trace"]["knowledge_lookup"]["status"] == "unavailable"
        assert context["retrieval_trace"]["knowledge_lookup"]["reason"] == (
            "timeout" if failure == "timeout" else "database_error"
        )
        assert context["memories"][0]["id"] == "existing"
        assert session.is_active
        assert await session.scalar(text("SELECT 1")) == 1
        assert await session.scalar(text("SHOW statement_timeout")) == previous_timeout
        run.trace = context["retrieval_trace"]
        await session.commit()

    async with database() as session:
        persisted = await session.get(ContextRun, run_id)
        assert persisted is not None
        assert persisted.status == "completed"
        assert persisted.trace["knowledge_lookup"]["status"] == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_timeout", [0, 50, 2000])
async def test_success_restores_timeout_and_never_relaxes_a_shorter_existing_timeout(
    database, test_user_id, monkeypatch, existing_timeout,
):
    observed_timeouts = []

    async def successful_lookup(session, **_kwargs):
        observed_timeouts.append(int(await session.scalar(text(
            "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'"
        ))))
        await session.execute(text("SELECT pg_sleep(0.01)"))
        return []

    monkeypatch.setattr("app.api.context_runtime.discover_knowledge_refs", successful_lookup)
    async with database() as session:
        await session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": str(existing_timeout)},
        )

        await _append_knowledge_refs(
            {"scope": "personal"}, UnifiedContextRequest(task="deployment"), session, test_user_id,
        )

        assert observed_timeouts == [min(existing_timeout or 500, 500)]
        assert int(await session.scalar(text(
            "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'"
        ))) == existing_timeout
        assert await session.scalar(text("SELECT 1")) == 1
        await session.commit()
