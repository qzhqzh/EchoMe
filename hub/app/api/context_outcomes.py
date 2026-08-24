"""Append-only context outcome API."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.project_knowledge import ContextOutcome, ContextRun, ProjectEvent
from app.schemas.context_outcome import ContextOutcomeBatchCreate, ContextOutcomeCreate

router = APIRouter(prefix="/context-outcomes", tags=["context-outcomes"])


def _payload(item: ContextOutcome) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "context_run_id": str(item.context_run_id),
        "outcome": item.outcome,
        "policy_effect": item.policy_effect,
        "reported_by": item.reported_by,
        "source": item.source,
        "project_event_id": str(item.project_event_id) if item.project_event_id else None,
        "note": item.note,
        "idempotency_key": item.idempotency_key,
        "created_at": item.created_at.isoformat(),
    }


async def _append(
    session: AsyncSession,
    body: ContextOutcomeCreate,
    user_id: str,
) -> ContextOutcome:
    run = await session.scalar(
        select(ContextRun).where(
            ContextRun.id == body.context_run_id, ContextRun.user_id == user_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Context run not found")
    if run.status != "completed" or run.shadow:
        raise HTTPException(status_code=422, detail="Outcomes require a completed, non-shadow run")
    policy = run.trace.get("context_policy") if isinstance(run.trace, dict) else None
    if body.policy_effect is not None and (
        not isinstance(policy, dict) or policy.get("effective_mode") not in {"shadow", "enforce"}
    ):
        raise HTTPException(
            status_code=422,
            detail="Policy effects require a context run with an observed context policy",
        )
    if body.project_event_id:
        event = await session.scalar(
            select(ProjectEvent).where(
                ProjectEvent.id == body.project_event_id,
                ProjectEvent.user_id == user_id,
            )
        )
        if event is None or run.project_id is None or event.project_id != run.project_id:
            raise HTTPException(
                status_code=422, detail="Project event does not belong to the context run"
            )
    statement = (
        insert(ContextOutcome)
        .values(user_id=user_id, **body.model_dump())
        .on_conflict_do_nothing(constraint="uq_context_outcome_idempotency")
        .returning(ContextOutcome)
    )
    outcome = await session.scalar(statement)
    if outcome is not None:
        return outcome
    existing = await session.scalar(
        select(ContextOutcome).where(
            ContextOutcome.user_id == user_id,
            ContextOutcome.context_run_id == body.context_run_id,
            ContextOutcome.idempotency_key == body.idempotency_key,
        )
    )
    if existing is None:
        raise HTTPException(
            status_code=409, detail="Context outcome conflict could not be resolved"
        )
    same_payload = all(
        getattr(existing, field) == getattr(body, field)
        for field in (
            "outcome",
            "policy_effect",
            "reported_by",
            "source",
            "project_event_id",
            "note",
        )
    )
    if not same_payload:
        raise HTTPException(status_code=409, detail="Idempotency key has a different payload")
    return existing


@router.post("", status_code=status.HTTP_201_CREATED)
async def append_context_outcome(
    body: ContextOutcomeCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    outcome = await _append(session, body, user_id)
    await session.flush()
    return _payload(outcome)


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def append_context_outcome_batch(
    body: ContextOutcomeBatchCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    outcomes = [await _append(session, item, user_id) for item in body.items]
    await session.flush()
    return {"items": [_payload(item) for item in outcomes]}


@router.get("")
async def list_context_outcomes(
    context_run_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    run = await session.scalar(
        select(ContextRun.id).where(
            ContextRun.id == context_run_id,
            ContextRun.user_id == user_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Context run not found")
    result = await session.execute(
        select(ContextOutcome)
        .where(
            ContextOutcome.user_id == user_id,
            ContextOutcome.context_run_id == context_run_id,
        )
        .order_by(ContextOutcome.created_at)
    )
    items = list(result.scalars().all())
    return {"total": len(items), "items": [_payload(item) for item in items]}
