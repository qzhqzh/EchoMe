"""Explicit context outcome contract tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.context_outcomes import _append
from app.models.project_knowledge import ContextOutcome, ContextRun
from app.schemas.context_outcome import ContextOutcomeBatchCreate, ContextOutcomeCreate


def _body(**overrides) -> ContextOutcomeCreate:
    values = {
        "context_run_id": uuid.uuid4(),
        "outcome": "success",
        "idempotency_key": "task-1",
    }
    values.update(overrides)
    return ContextOutcomeCreate(**values)


def test_corrected_outcome_requires_evidence_note() -> None:
    with pytest.raises(ValidationError, match="require a note"):
        _body(outcome="corrected", note="   ")


def test_harmful_policy_effect_requires_evidence_note() -> None:
    with pytest.raises(ValidationError, match="harmful policy effects require a note"):
        _body(policy_effect="harmful")


def test_batch_rejects_duplicate_run_idempotency_key() -> None:
    run_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="duplicate context run"):
        ContextOutcomeBatchCreate(
            items=[
                _body(context_run_id=run_id),
                _body(context_run_id=run_id, outcome="partial"),
            ]
        )


@pytest.mark.asyncio
async def test_outcome_requires_completed_non_shadow_run() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(
        return_value=ContextRun(
            user_id="user",
            query="task",
            mode="personal",
            token_budget=1000,
            shadow=True,
        )
    )

    with pytest.raises(HTTPException) as error:
        await _append(session, _body(), "user")

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_outcome_idempotency_returns_existing_signal() -> None:
    body = _body()
    run = ContextRun(
        id=body.context_run_id,
        user_id="user",
        query="task",
        mode="personal",
        token_budget=1000,
        status="completed",
        shadow=False,
    )
    existing = ContextOutcome(user_id="user", **body.model_dump())
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[run, None, existing])

    result = await _append(session, body, "user")

    assert result is existing


@pytest.mark.asyncio
async def test_policy_effect_requires_observed_policy_trace() -> None:
    body = _body(policy_effect="helpful")
    run = ContextRun(
        id=body.context_run_id,
        user_id="user",
        query="task",
        mode="personal",
        token_budget=1000,
        status="completed",
        shadow=False,
        trace={},
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=run)

    with pytest.raises(HTTPException) as error:
        await _append(session, body, "user")

    assert error.value.status_code == 422
    assert "observed context policy" in error.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("effective_mode", [None, "", "unknown", "off"])
async def test_policy_effect_requires_shadow_or_enforce_mode(
    effective_mode: str | None,
) -> None:
    body = _body(policy_effect="helpful")
    run = ContextRun(
        id=body.context_run_id,
        user_id="user",
        query="task",
        mode="personal",
        token_budget=1000,
        status="completed",
        shadow=False,
        trace={"context_policy": {"effective_mode": effective_mode}},
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=run)

    with pytest.raises(HTTPException) as error:
        await _append(session, body, "user")

    assert error.value.status_code == 422
