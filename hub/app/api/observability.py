"""Read-only observability API for memory governance."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory, MemoryEdge, MemoryFeedback, SleepSession

router = APIRouter(prefix="/observability", tags=["observability"])

ACTIVE_STATUSES = {"active", "ai_review", "pending"}
TEMPORAL_KEYWORDS = {
    "temporary",
    "temp",
    "current",
    "currently",
    "old",
    "legacy",
    "workaround",
    "phase",
    "临时",
    "当前",
    "现在",
    "旧",
    "老",
    "已恢复",
    "阶段",
    "过渡",
}
STABLE_TAGS = {
    "guardrail",
    "decision",
    "architecture",
    "workflow",
    "stack",
    "method",
    "规范",
    "架构",
}


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
        "access_count": memory.access_count,
        "last_accessed_at": memory.last_accessed_at.isoformat()
        if memory.last_accessed_at
        else None,
        "created_at": memory.created_at.isoformat(),
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


def _memory_detail(memory: Memory) -> dict[str, Any]:
    payload = _memory_node(memory)
    payload.update(
        {
            "content": memory.content,
            "priority": memory.priority,
            "source": memory.source,
            "scope": {
                "global": memory.scope_global,
                "projects": memory.scope_projects,
                "exclude_projects": memory.scope_exclude,
            },
            "token_count": memory.token_count,
        }
    )
    return payload


async def _feedback_summary(
    session: AsyncSession,
    memory_id: uuid.UUID,
    user_id: str,
) -> dict[str, Any]:
    result = await session.execute(
        select(
            MemoryFeedback.rating,
            func.count(MemoryFeedback.id),
            func.max(MemoryFeedback.created_at),
        )
        .where(MemoryFeedback.memory_id == memory_id, MemoryFeedback.user_id == user_id)
        .group_by(MemoryFeedback.rating)
    )
    rows = result.all()
    ratings = {rating: count for rating, count, _ in rows}
    last_feedback_at = max((last_at for _, _, last_at in rows if last_at is not None), default=None)
    return {
        "total": sum(ratings.values()),
        "ratings": ratings,
        "last_feedback_at": last_feedback_at.isoformat() if last_feedback_at else None,
    }


def _days_since(value: datetime | None) -> int | None:
    if not value:
        return None
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max((now - value).days, 0)


def _project_keys(memory: Memory) -> list[str]:
    return list(memory.scope_projects or [])


def _project_activity_map(memories: list[Memory]) -> dict[str, datetime]:
    activity: dict[str, datetime] = {}
    for memory in memories:
        for project_id in _project_keys(memory):
            current = activity.get(project_id)
            if current is None or memory.updated_at > current:
                activity[project_id] = memory.updated_at
    return activity


def _project_activity_at(
    memory: Memory,
    project_activity: dict[str, datetime],
) -> datetime | None:
    dates = [project_activity[p] for p in _project_keys(memory) if p in project_activity]
    return max(dates) if dates else None


def _temporal_assessment(
    memory: Memory,
    project_activity_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a conservative, evidence-based temporal read for one memory."""
    updated_age_days = _days_since(memory.updated_at)
    accessed_age_days = _days_since(memory.last_accessed_at)
    project_age_days = _days_since(project_activity_at)
    text = " ".join(
        [
            memory.title,
            memory.content[:1000],
            " ".join(str(tag) for tag in memory.tags),
        ]
    ).lower()

    signals: list[str] = []
    if memory.status in {"archived", "deprecated"}:
        signals.append(f"status:{memory.status}")
    if memory.sleep_state == "superseded" or memory.superseded_by:
        signals.append("superseded")

    matched_temporal_terms = sorted(term for term in TEMPORAL_KEYWORDS if term in text)
    if matched_temporal_terms:
        signals.append("temporal_terms:" + ",".join(matched_temporal_terms[:5]))

    stable_signals: list[str] = []
    if memory.is_core:
        stable_signals.append("core")
    if memory.layer in {"L0", "L1"}:
        stable_signals.append(f"layer:{memory.layer}")
    if memory.sleep_state in {"reviewed", "distilled"}:
        stable_signals.append(f"sleep_state:{memory.sleep_state}")
    if memory.priority >= 8:
        stable_signals.append("high_priority")
    if set(str(tag).lower() for tag in memory.tags) & STABLE_TAGS:
        stable_signals.append("stable_tags")

    if memory.status in {"archived", "deprecated"} or memory.sleep_state == "superseded":
        classification = "superseded_or_inactive"
        confidence = "high"
    elif matched_temporal_terms and not stable_signals:
        classification = "needs_verification"
        confidence = "medium"
    elif matched_temporal_terms and stable_signals:
        classification = "stable_but_time_sensitive"
        confidence = "medium"
    elif project_age_days is not None and project_age_days >= 180:
        classification = "dormant_project"
        confidence = "low"
        signals.append("project_dormant_not_stale")
    elif updated_age_days is not None and updated_age_days >= 365 and not stable_signals:
        classification = "low_access_review"
        confidence = "low"
        signals.append("old_memory_without_other_stale_evidence")
    elif stable_signals:
        classification = "stable"
        confidence = "medium"
    else:
        classification = "fresh_or_unclassified"
        confidence = "low"

    return {
        "classification": classification,
        "confidence": confidence,
        "signals": signals,
        "stable_signals": stable_signals,
        "updated_age_days": updated_age_days,
        "accessed_age_days": accessed_age_days,
        "project_activity_age_days": project_age_days,
        "note": (
            "Long inactivity alone is not treated as stale; dormant projects are separated "
            "from time-sensitive or superseded memories."
        ),
    }


async def _get_memory_or_404(
    session: AsyncSession,
    memory_id: uuid.UUID,
    user_id: str,
) -> Memory:
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return memory


async def _get_memories_by_ids(
    session: AsyncSession,
    memory_ids: set[uuid.UUID],
    user_id: str,
    include_inactive: bool,
) -> list[Memory]:
    if not memory_ids:
        return []
    query = select(Memory).where(Memory.user_id == user_id, Memory.id.in_(memory_ids))
    if not include_inactive:
        query = query.where(Memory.status.in_(list(ACTIVE_STATUSES)))
    result = await session.execute(query)
    return list(result.scalars().all())


async def _get_edges_touching(
    session: AsyncSession,
    memory_ids: set[uuid.UUID],
    user_id: str,
) -> list[MemoryEdge]:
    if not memory_ids:
        return []
    result = await session.execute(
        select(MemoryEdge)
        .where(MemoryEdge.user_id == user_id)
        .where(
            or_(
                MemoryEdge.source_memory_id.in_(memory_ids),
                MemoryEdge.target_memory_id.in_(memory_ids),
            )
        )
    )
    return list(result.scalars().all())


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


@router.get("/memory-graph/neighbors/{memory_id}")
async def get_memory_neighbors(
    memory_id: uuid.UUID,
    depth: int = Query(1, ge=1, le=3),
    include_inactive: bool = Query(False, alias="include_inactive"),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """Return an AI-readable local memory graph around one memory."""
    center = await _get_memory_or_404(session, memory_id, user_id)
    seen_ids = {center.id}
    frontier = {center.id}
    edge_by_id: dict[uuid.UUID, MemoryEdge] = {}

    for _ in range(depth):
        if len(seen_ids) >= limit:
            break
        edges = await _get_edges_touching(session, frontier, user_id)
        next_frontier: set[uuid.UUID] = set()
        for edge in edges:
            edge_by_id[edge.id] = edge
            for endpoint in (edge.source_memory_id, edge.target_memory_id):
                if endpoint not in seen_ids and len(seen_ids) < limit:
                    next_frontier.add(endpoint)
                    seen_ids.add(endpoint)
        frontier = next_frontier
        if not frontier:
            break

    memories = await _get_memories_by_ids(session, seen_ids, user_id, include_inactive)
    memory_ids = {m.id for m in memories}
    visible_edges = [
        edge
        for edge in edge_by_id.values()
        if edge.source_memory_id in memory_ids and edge.target_memory_id in memory_ids
    ]
    project_activity = _project_activity_map(memories)

    return {
        "center_memory_id": str(center.id),
        "depth": depth,
        "include_inactive": include_inactive,
        "nodes": [_memory_detail(m) for m in memories],
        "edges": [_edge_payload(edge) for edge in visible_edges],
        "temporal_assessments": {
            str(m.id): _temporal_assessment(m, _project_activity_at(m, project_activity))
            for m in memories
        },
    }


@router.get("/memory-graph/explain/{memory_id}")
async def explain_memory(
    memory_id: uuid.UUID,
    include_inactive: bool = Query(True, alias="include_inactive"),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """Explain one memory with provenance, successors, and temporal status."""
    memory = await _get_memory_or_404(session, memory_id, user_id)
    edges = await _get_edges_touching(session, {memory.id}, user_id)
    related_ids = {
        endpoint
        for edge in edges
        for endpoint in (edge.source_memory_id, edge.target_memory_id)
        if endpoint != memory.id
    }
    related_memories = await _get_memories_by_ids(
        session,
        related_ids | {memory.id},
        user_id,
        include_inactive,
    )
    project_activity = _project_activity_map(related_memories)

    incoming = [edge for edge in edges if edge.target_memory_id == memory.id]
    outgoing = [edge for edge in edges if edge.source_memory_id == memory.id]

    return {
        "memory": _memory_detail(memory),
        "temporal_assessment": _temporal_assessment(
            memory,
            _project_activity_at(memory, project_activity),
        ),
        "incoming_edges": [_edge_payload(edge) for edge in incoming],
        "outgoing_edges": [_edge_payload(edge) for edge in outgoing],
        "related_memories": [
            _memory_node(related) for related in related_memories if related.id != memory.id
        ],
        "feedback_summary": await _feedback_summary(session, memory.id, user_id),
        "ai_summary": {
            "why_this_memory_exists": "Use incoming derived_from/specializes edges as provenance.",
            "what_it_replaces": "Use outgoing superseded_by/supersedes edges as replacement signals.",
            "temporal_note": (
                "The temporal assessment is evidence-based. Dormant project age is separated "
                "from actual stale evidence."
            ),
        },
    }


@router.get("/memory-graph/temporal-candidates")
async def list_temporal_candidates(
    project_id: str | None = None,
    include_inactive: bool = Query(False, alias="include_inactive"),
    classifications: str | None = Query(
        None,
        description="Comma-separated classifications to include.",
    ),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """List memories that may need temporal review without changing their status."""
    query = select(Memory).where(Memory.user_id == user_id)
    if project_id:
        query = query.where(Memory.scope_projects.contains([project_id]))
    if not include_inactive:
        query = query.where(Memory.status.in_(list(ACTIVE_STATUSES)))

    result = await session.execute(query.order_by(Memory.updated_at.desc()))
    memories = list(result.scalars().all())
    project_activity = _project_activity_map(memories)
    allowed = {item.strip() for item in classifications.split(",")} if classifications else None

    items: list[dict[str, Any]] = []
    for memory in memories:
        assessment = _temporal_assessment(memory, _project_activity_at(memory, project_activity))
        if allowed and assessment["classification"] not in allowed:
            continue
        if not allowed and assessment["classification"] in {"stable", "fresh_or_unclassified"}:
            continue
        items.append(
            {
                "memory": _memory_node(memory),
                "temporal_assessment": assessment,
            }
        )
        if len(items) >= limit:
            break

    return {
        "total_scanned": len(memories),
        "items": items,
        "policy": {
            "long_unaccessed_is_not_stale": True,
            "project_dormancy_is_reported_separately": True,
            "status_mutation": "none",
        },
    }
