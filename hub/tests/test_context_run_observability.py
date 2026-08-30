"""Context Run observability includes the result evidence that closes the loop."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.project_knowledge import list_context_runs
from app.models.project_knowledge import ContextOutcome, ContextRun


@pytest.mark.asyncio
async def test_context_runs_include_append_only_outcomes() -> None:
    run = ContextRun(
        id=uuid.uuid4(),
        user_id="user",
        query="verify release",
        mode="local",
        token_budget=1000,
        created_at=datetime.now(timezone.utc),
    )
    outcome = ContextOutcome(
        id=uuid.uuid4(),
        user_id="user",
        context_run_id=run.id,
        outcome="success",
        policy_effect="helpful",
        reported_by="ai",
        source="mcp",
        idempotency_key="completion",
        created_at=datetime.now(timezone.utc),
    )
    run_result = MagicMock()
    run_result.scalars.return_value.all.return_value = [run]
    outcome_result = MagicMock()
    outcome_result.scalars.return_value.all.return_value = [outcome]
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[run_result, outcome_result])

    payload = await list_context_runs(project_id=None, limit=100, session=session, user_id="user")

    assert payload["total"] == 1
    assert payload["items"][0]["outcomes"] == [
        {
            "id": str(outcome.id),
            "outcome": "success",
            "policy_effect": "helpful",
            "reported_by": "ai",
            "source": "mcp",
            "note": None,
            "created_at": outcome.created_at.isoformat(),
        }
    ]
