"""Read-only observability API for memory governance."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory, MemoryEdge, SleepSession

router = APIRouter(prefix="/observability", tags=["observability"])


def _memory_node(memory: Memory) -> dict[str, Any]:
    return {
        "id": str(memory.id),
        "title": memory.title,
        "type": memory.type,
        "layer": memory.layer,
        "status": memory.status,
        "tags": memory.tags,
        "is_core": memory.is_core,
        "sleep_state": memory.sleep_state,
        "superseded_by": str(memory.superseded_by) if memory.superseded_by else None,
        "derived_from": memory.derived_from,
        "updated_at": memory.updated_at.isoformat(),
    }


def _edge_payload(edge: MemoryEdge) -> dict[str, Any]:
    return {
        "id": str(edge.id),
        "source_memory_id": str(edge.source_memory_id),
        "target_memory_id": str(edge.target_memory_id),
        "relation": edge.relation,
        "reason": edge.reason,
        "sleep_session_id": str(edge.sleep_session_id) if edge.sleep_session_id else None,
        "created_by": edge.created_by,
        "created_at": edge.created_at.isoformat(),
    }


def _sleep_session_payload(sleep_session: SleepSession) -> dict[str, Any]:
    return {
        "id": str(sleep_session.id),
        "project_id": sleep_session.project_id,
        "status": sleep_session.status,
        "mode": sleep_session.mode,
        "candidate_count": len(sleep_session.candidate_memory_ids),
        "created_at": sleep_session.created_at.isoformat(),
        "updated_at": sleep_session.updated_at.isoformat(),
        "applied_at": sleep_session.applied_at.isoformat() if sleep_session.applied_at else None,
    }


@router.get("/sleep-sessions")
async def list_sleep_sessions(
    project_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """List Memory Sleep sessions for the current user."""
    query = select(SleepSession).where(SleepSession.user_id == user_id)
    if project_id:
        query = query.where(SleepSession.project_id == project_id)
    if status_filter:
        query = query.where(SleepSession.status == status_filter)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await session.execute(
        query.order_by(SleepSession.created_at.desc()).offset(offset).limit(limit)
    )
    sessions = result.scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_sleep_session_payload(s) for s in sessions],
    }


@router.get("/sleep-sessions/{session_id}")
async def get_sleep_session_detail(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """Get one Memory Sleep session with proposal and relation edges."""
    result = await session.execute(
        select(SleepSession).where(
            SleepSession.id == session_id,
            SleepSession.user_id == user_id,
        )
    )
    sleep_session = result.scalar_one_or_none()
    if not sleep_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sleep session not found",
        )

    edge_result = await session.execute(
        select(MemoryEdge).where(
            MemoryEdge.user_id == user_id,
            MemoryEdge.sleep_session_id == session_id,
        )
    )
    edges = edge_result.scalars().all()

    payload = _sleep_session_payload(sleep_session)
    payload.update(
        {
            "candidate_memory_ids": sleep_session.candidate_memory_ids,
            "text_proposal": sleep_session.text_proposal,
            "json_proposal": sleep_session.json_proposal,
            "edges": [_edge_payload(e) for e in edges],
        }
    )
    return payload


@router.get("/memory-graph")
async def get_memory_graph(
    project_id: str | None = None,
    include_inactive: bool = Query(False, alias="include_inactive"),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """Return memory nodes and relation edges for graph visualization."""
    query = select(Memory).where(Memory.user_id == user_id)
    if project_id:
        query = query.where(Memory.scope_projects.contains([project_id]))
    if not include_inactive:
        query = query.where(Memory.status.in_(["active", "ai_review", "pending"]))

    result = await session.execute(query.order_by(Memory.updated_at.desc()))
    memories = result.scalars().all()
    memory_ids = {m.id for m in memories}

    edges: list[MemoryEdge] = []
    if memory_ids:
        edge_result = await session.execute(
            select(MemoryEdge)
            .where(MemoryEdge.user_id == user_id)
            .where(
                or_(
                    MemoryEdge.source_memory_id.in_(memory_ids),
                    MemoryEdge.target_memory_id.in_(memory_ids),
                )
            )
        )
        edges = list(edge_result.scalars().all())

    return {
        "nodes": [_memory_node(m) for m in memories],
        "edges": [_edge_payload(e) for e in edges],
    }
