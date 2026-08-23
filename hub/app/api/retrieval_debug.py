"""Retrieval debugger and retrieval log API."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.memories import _query_tokens
from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory, RetrievalLog
from app.schemas.retrieval_debug import (
    RetrievalDebugRequest,
    RetrievalLogCreate,
    RetrievalLogListResponse,
    RetrievalLogResponse,
)
from app.services.memory_retrieval import retrieve_memories

router = APIRouter(prefix="/retrieval-debug", tags=["retrieval-debug"])

_RESULT_LOG_FIELDS = {
    "id",
    "title",
    "type",
    "layer",
    "status",
    "priority",
    "tags",
    "updated_at",
    "score",
    "reasons",
}
_STEP_LOG_FIELDS = {
    "stage",
    "strategy",
    "vector_available",
    "vector_count",
    "lexical_count",
    "lexical_candidate_count",
    "selected_count",
    "count",
    "used",
    "tokens",
}


def _memory_payload(
    memory: Memory,
    score: float | None = None,
    reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload = {
        "id": str(memory.id),
        "title": memory.title,
        "type": memory.type,
        "layer": memory.layer,
        "status": memory.status,
        "priority": memory.priority,
        "tags": memory.tags,
        "updated_at": memory.updated_at.isoformat(),
        "reasons": list(reasons),
    }
    if score is not None:
        payload["score"] = round(score, 4)
    return payload


def _expected_rank(items: list[dict[str, Any]], expected_ids: list[str]) -> int | None:
    expected = set(expected_ids)
    for index, item in enumerate(items, 1):
        if item["id"] in expected:
            return index
    return None


def _bounded_log_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:512]
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [
            bounded
            for item in value[:64]
            if not isinstance(item, dict | list)
            for bounded in [_bounded_log_value(item)]
        ]
    return None


def _sanitize_log_record(item: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {
        key: bounded
        for key, value in item.items()
        if key in allowed
        for bounded in [_bounded_log_value(value)]
        if bounded is not None
    }


def _log_response(log: RetrievalLog) -> RetrievalLogResponse:
    return RetrievalLogResponse.model_validate(log)


async def _save_log(
    session: AsyncSession,
    user_id: str,
    payload: RetrievalLogCreate,
) -> RetrievalLog:
    top_results = [
        _sanitize_log_record(item, _RESULT_LOG_FIELDS) for item in payload.top_results
    ]
    steps = [_sanitize_log_record(item, _STEP_LOG_FIELDS) for item in payload.steps]
    log = RetrievalLog(
        user_id=user_id,
        query=payload.query,
        client=payload.client,
        source=payload.source,
        status_filter=payload.status,
        project_id=payload.project_id,
        limit=payload.limit,
        lightweight_count=payload.lightweight_count,
        semantic_count=payload.semantic_count,
        fallback_used=payload.fallback_used,
        expected_ids=payload.expected_ids,
        expected_rank=payload.expected_rank,
        top_results=top_results,
        steps=steps,
    )
    session.add(log)
    await session.flush()
    return log


@router.post("/query", response_model=RetrievalLogResponse)
async def debug_query(
    body: RetrievalDebugRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> RetrievalLogResponse:
    """Run a retrieval debug query and persist the intermediate steps."""
    retrieval = await retrieve_memories(
        session,
        user_id=user_id,
        query=body.query,
        limit=body.limit,
        statuses=(body.status,) if body.status else ("active", "ai_review"),
        global_only=body.project_id is None,
        project_scope_ids=[body.project_id] if body.project_id else None,
    )
    top_results = [
        _memory_payload(item.memory, item.score, item.reasons) for item in retrieval.items
    ]
    steps = [{"stage": "hybrid_memory", **retrieval.trace, "tokens": _query_tokens(body.query)}]
    fallback_used = not bool(retrieval.trace["vector_available"])

    expected_ids = [str(item) for item in body.expected_ids]
    log = await _save_log(
        session,
        user_id,
        RetrievalLogCreate(
            query=body.query,
            client=body.client,
            source=body.source,
            status=body.status,
            project_id=body.project_id,
            limit=body.limit,
            lightweight_count=int(retrieval.trace["lexical_count"]),
            semantic_count=int(retrieval.trace["vector_count"]),
            fallback_used=fallback_used,
            expected_ids=expected_ids,
            expected_rank=_expected_rank(top_results, expected_ids),
            top_results=top_results,
            steps=steps,
        ),
    )
    return _log_response(log)


@router.post("/logs", response_model=RetrievalLogResponse)
async def create_log(
    body: RetrievalLogCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> RetrievalLogResponse:
    """Record a retrieval log from MCP or another client."""
    return _log_response(await _save_log(session, user_id, body))


@router.get("/logs", response_model=RetrievalLogListResponse)
async def list_logs(
    client: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> RetrievalLogListResponse:
    """List recent retrieval logs."""
    query = select(RetrievalLog).where(RetrievalLog.user_id == user_id)
    if client:
        query = query.where(RetrievalLog.client == client)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await session.execute(query.order_by(RetrievalLog.created_at.desc()).limit(limit))
    return RetrievalLogListResponse(
        total=total,
        items=[_log_response(log) for log in result.scalars().all()],
    )
