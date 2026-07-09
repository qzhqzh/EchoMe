"""Retrieval debugger and retrieval log API."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, case, func, or_, select
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
from app.services.embedding import get_embedding

router = APIRouter(prefix="/retrieval-debug", tags=["retrieval-debug"])


def _memory_payload(memory: Memory, score: float | None = None) -> dict[str, Any]:
    payload = {
        "id": str(memory.id),
        "title": memory.title,
        "type": memory.type,
        "layer": memory.layer,
        "status": memory.status,
        "priority": memory.priority,
        "tags": memory.tags,
        "updated_at": memory.updated_at.isoformat(),
        "content": memory.content,
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


async def _lightweight_search(
    session: AsyncSession,
    body: RetrievalDebugRequest,
    user_id: str,
) -> list[Memory]:
    query = select(Memory).where(Memory.user_id == user_id)
    if body.status:
        query = query.where(Memory.status == body.status)
    if body.project_id:
        query = query.where(Memory.scope_projects.contains([body.project_id]))

    title_field = func.lower(Memory.title)
    content_field = func.lower(Memory.content)
    tags_field = func.lower(Memory.tags.cast(String))
    patterns = [f"%{body.query.lower()}%"]
    patterns.extend(f"%{token}%" for token in _query_tokens(body.query))
    query = query.where(
        or_(
            *[
                field.like(pattern)
                for pattern in patterns
                for field in (title_field, content_field, tags_field)
            ]
        )
    )
    relevance = sum(
        case((title_field.like(pattern), 5), else_=0)
        + case((tags_field.like(pattern), 4), else_=0)
        + case((content_field.like(pattern), 1), else_=0)
        for pattern in patterns
    )
    result = await session.execute(
        query.order_by(relevance.desc(), Memory.priority.desc(), Memory.updated_at.desc()).limit(body.limit)
    )
    return list(result.scalars().all())


async def _semantic_search(
    session: AsyncSession,
    body: RetrievalDebugRequest,
    user_id: str,
) -> list[tuple[Memory, float]]:
    base_filter = [Memory.user_id == user_id, Memory.status.in_(["active", "ai_review"])]
    if body.project_id:
        base_filter.append(
            (Memory.scope_global.is_(True)) | (Memory.scope_projects.contains([body.project_id]))
        )

    query_embedding = await get_embedding(body.query)
    scored: dict[uuid.UUID, tuple[Memory, float]] = {}
    if query_embedding is not None:
        vector_query = (
            select(
                Memory,
                Memory.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(*base_filter)
            .where(Memory.embedding.isnot(None))
            .order_by("distance")
            .limit(body.limit * 2)
        )
        result = await session.execute(vector_query)
        for row in result:
            similarity = 1.0 - row[1]
            if similarity >= 0.3:
                scored[row[0].id] = (row[0], similarity * 0.7)

    keyword_query = select(Memory).where(*base_filter)
    result = await session.execute(keyword_query)
    words = body.query.lower().split()
    for memory in result.scalars().all():
        searchable = f"{memory.title} {memory.content} {' '.join(memory.tags)}".lower()
        matches = sum(1 for word in words if word in searchable)
        score = matches / len(words) if words else 0.0
        if score < 0.3:
            continue
        if memory.id in scored:
            existing, existing_score = scored[memory.id]
            scored[memory.id] = (existing, existing_score + score * 0.3)
        else:
            scored[memory.id] = (memory, score * 0.3)

    return sorted(scored.values(), key=lambda item: item[1], reverse=True)[: body.limit]


def _log_response(log: RetrievalLog) -> RetrievalLogResponse:
    return RetrievalLogResponse.model_validate(log)


async def _save_log(
    session: AsyncSession,
    user_id: str,
    payload: RetrievalLogCreate,
) -> RetrievalLog:
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
        top_results=payload.top_results,
        steps=payload.steps,
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
    steps: list[dict[str, Any]] = []
    lightweight = await _lightweight_search(session, body, user_id)
    steps.append(
        {
            "stage": "lightweight",
            "count": len(lightweight),
            "tokens": _query_tokens(body.query),
        }
    )
    fallback_used = len(lightweight) == 0
    semantic: list[tuple[Memory, float]] = []
    if fallback_used:
        semantic = await _semantic_search(session, body, user_id)
        steps.append({"stage": "semantic_fallback", "count": len(semantic)})

    if fallback_used:
        top_results = [_memory_payload(memory, score) for memory, score in semantic]
    else:
        top_results = [_memory_payload(memory) for memory in lightweight]

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
            lightweight_count=len(lightweight),
            semantic_count=len(semantic),
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
