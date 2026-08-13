"""Memory Sleep API routes."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.memories import _compute_and_store_embedding
from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory, MemoryEdge, SleepSession
from app.schemas.sleep import (
    SleepApplyRequest,
    SleepApplyResponse,
    SleepCandidatesRequest,
    SleepCandidatesResponse,
    SleepEdgeItem,
    SleepMemoryItem,
    SleepProposalSubmitRequest,
    SleepSessionResponse,
)
from app.services.project_identity import (
    canonicalize_project_scopes,
    project_scope_ids,
)
from app.services.token_counter import count_tokens

router = APIRouter(prefix="/memory-sleep", tags=["memory-sleep"])

PLAN_SCHEMA_VERSION = "memory_sleep_plan.v1"
ORGANIZED_STATES = {"reviewed", "distilled", "superseded"}
ALLOWED_STATUS_UPDATES = {"archived", "deprecated"}


def _plan_json_schema() -> dict[str, Any]:
    """Return the minimal JSON plan contract clients must submit."""
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "required": ["schema_version", "session_id", "input_memory_ids", "actions"],
        "actions": [
            "create_memory",
            "update_memory_status",
            "create_edge",
            "keep_memory",
            "needs_human",
        ],
    }


def _scope_payload(memory: Memory) -> dict[str, Any]:
    return {
        "global": memory.scope_global,
        "projects": memory.scope_projects,
        "exclude_projects": memory.scope_exclude,
    }


def _memory_item(memory: Memory, protection_reason: str | None = None) -> SleepMemoryItem:
    return SleepMemoryItem(
        id=memory.id,
        title=memory.title,
        content=memory.content,
        type=memory.type,
        layer=memory.layer,
        priority=memory.priority,
        tags=memory.tags,
        status=memory.status,
        source=memory.source,
        scope=_scope_payload(memory),
        is_core=memory.is_core,
        sleep_state=memory.sleep_state,
        access_count=memory.access_count,
        last_accessed_at=memory.last_accessed_at,
        superseded_by=memory.superseded_by,
        derived_from=memory.derived_from,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        protection_reason=protection_reason,
    )


def _edge_item(edge: MemoryEdge) -> SleepEdgeItem:
    return SleepEdgeItem(
        id=edge.id,
        source_memory_id=edge.source_memory_id,
        target_memory_id=edge.target_memory_id,
        relation=edge.relation,
        reason=edge.reason,
        sleep_session_id=edge.sleep_session_id,
        created_at=edge.created_at,
    )


def _candidate_filter(
    query: Any,
    body: SleepCandidatesRequest,
    user_id: str,
    scope_project_ids: list[str] | None = None,
) -> Any:
    query = query.where(
        Memory.user_id == user_id,
        Memory.status.in_([s.value for s in body.status]),
    )
    if body.scope == "project":
        if not body.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="project_id is required when scope is project",
            )
        assert body.project_id is not None
        project_ids = scope_project_ids or [body.project_id]
        query = query.where(
            or_(*(Memory.scope_projects.contains([project_id]) for project_id in project_ids))
        )
    elif body.scope == "global":
        query = query.where(Memory.scope_global.is_(True))
    return query


def _protection_reason(memory: Memory) -> str | None:
    if memory.is_core:
        return "core"
    if memory.sleep_state in ORGANIZED_STATES:
        return "already_organized"
    return None


@router.post("/candidates", response_model=SleepCandidatesResponse)
async def get_sleep_candidates(
    body: SleepCandidatesRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> SleepCandidatesResponse:
    """Return all eligible memory candidates page by page for client-side planning."""
    offset = body.cursor or 0
    canonical_project_id = body.project_id
    scope_ids: list[str] | None = None
    if body.scope == "project" and body.project_id:
        canonical = await canonicalize_project_scopes(
            session, user_id, [body.project_id]
        )
        canonical_project_id = canonical[0]
        scope_ids = await project_scope_ids(session, user_id, canonical_project_id)
    base_query = _candidate_filter(select(Memory), body, user_id, scope_ids)
    base_query = base_query.order_by(Memory.updated_at.desc(), Memory.id)

    result = await session.execute(base_query)
    all_memories = list(result.scalars().all())

    candidates = [m for m in all_memories if _protection_reason(m) is None]
    protected = [m for m in all_memories if _protection_reason(m) is not None]
    page = candidates[offset : offset + body.page_size]
    has_more = offset + body.page_size < len(candidates)
    next_cursor = offset + body.page_size if has_more else None

    if body.session_id:
        sleep_session = await _get_sleep_session(session, body.session_id, user_id)
        if sleep_session.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only draft sleep sessions can fetch more candidates",
            )
        sleep_session.candidate_memory_ids = [str(m.id) for m in candidates]
    else:
        sleep_session = SleepSession(
            user_id=user_id,
            project_id=canonical_project_id,
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(m.id) for m in candidates],
            created_by={"actor": "client"},
        )
        session.add(sleep_session)
        await session.flush()

    edge_memory_ids = {m.id for m in page}
    if body.include_protected:
        edge_memory_ids.update(m.id for m in protected)

    edges: list[MemoryEdge] = []
    if edge_memory_ids:
        edge_result = await session.execute(
            select(MemoryEdge)
            .where(MemoryEdge.user_id == user_id)
            .where(
                or_(
                    MemoryEdge.source_memory_id.in_(edge_memory_ids),
                    MemoryEdge.target_memory_id.in_(edge_memory_ids),
                )
            )
        )
        edges = list(edge_result.scalars().all())

    await session.commit()

    return SleepCandidatesResponse(
        session_id=sleep_session.id,
        project_id=canonical_project_id,
        candidates=[_memory_item(m) for m in page],
        protected_memories=[
            _memory_item(m, _protection_reason(m)) for m in protected
        ]
        if body.include_protected
        else [],
        relation_edges=[_edge_item(e) for e in edges],
        json_schema=_plan_json_schema(),
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/sessions/{session_id}/proposal", response_model=SleepSessionResponse)
async def submit_sleep_proposal(
    session_id: uuid.UUID,
    body: SleepProposalSubmitRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> SleepSessionResponse:
    """Attach a client-generated proposal to a sleep session."""
    sleep_session = await _get_sleep_session(session, session_id, user_id)
    if sleep_session.status in {"applied", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update a finalized sleep session",
        )

    _validate_plan_header(body.json_proposal, sleep_session)
    sleep_session.text_proposal = body.text_proposal
    sleep_session.json_proposal = body.json_proposal
    sleep_session.status = "proposed"
    await session.commit()

    return _session_response(sleep_session)


@router.post("/sessions/{session_id}/apply", response_model=SleepApplyResponse)
async def apply_sleep_proposal(
    session_id: uuid.UUID,
    body: SleepApplyRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> SleepApplyResponse:
    """Apply an approved sleep proposal."""
    sleep_session = await _get_sleep_session(session, session_id, user_id)
    if sleep_session.status == "applied":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sleep session is already applied",
        )
    if not body.approved:
        sleep_session.status = "rejected"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approved must be true to apply a sleep plan",
        )
    if not sleep_session.json_proposal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sleep session has no JSON proposal",
        )

    plan = sleep_session.json_proposal
    _validate_plan_header(plan, sleep_session)

    created_refs: dict[str, uuid.UUID] = {}
    created_memory_ids: list[uuid.UUID] = []
    created_memory_embeddings: list[tuple[uuid.UUID, str]] = []
    updated_memory_ids: list[uuid.UUID] = []
    edge_ids: list[uuid.UUID] = []

    for action in plan.get("actions", []):
        if action.get("op") == "create_memory":
            memory_id, embed_text, edge_ids_for_memory = await _apply_create_memory(
                session, user_id, sleep_session, action
            )
            client_ref = action.get("client_ref")
            if client_ref:
                created_refs[client_ref] = memory_id
            created_memory_ids.append(memory_id)
            created_memory_embeddings.append((memory_id, embed_text))
            edge_ids.extend(edge_ids_for_memory)

    await session.flush()

    for action in plan.get("actions", []):
        op = action.get("op")
        if op == "update_memory_status":
            memory_id, edge_id = await _apply_status_update(
                session, user_id, sleep_session, action, created_refs
            )
            updated_memory_ids.append(memory_id)
            if edge_id:
                edge_ids.append(edge_id)
        elif op == "keep_memory":
            memory_id = await _apply_keep_memory(session, user_id, action)
            updated_memory_ids.append(memory_id)
        elif op == "create_edge":
            edge_id = await _apply_create_edge(
                session, user_id, sleep_session, action, created_refs
            )
            edge_ids.append(edge_id)
        elif op in {"create_memory", "needs_human"}:
            continue
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported sleep action: {op}",
            )

    sleep_session.status = "applied"
    sleep_session.applied_at = datetime.now(timezone.utc)
    await session.commit()

    for memory_id, embed_text in created_memory_embeddings:
        background_tasks.add_task(_compute_and_store_embedding, memory_id, embed_text)

    return SleepApplyResponse(
        session_id=sleep_session.id,
        status="applied",
        created_memory_ids=created_memory_ids,
        updated_memory_ids=updated_memory_ids,
        edge_ids=edge_ids,
    )


async def _get_sleep_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: str
) -> SleepSession:
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
    return sleep_session


def _session_response(sleep_session: SleepSession) -> SleepSessionResponse:
    return SleepSessionResponse(
        session_id=sleep_session.id,
        status=sleep_session.status,
        mode=sleep_session.mode,
        project_id=sleep_session.project_id,
        candidate_memory_ids=sleep_session.candidate_memory_ids,
        text_proposal=sleep_session.text_proposal,
        json_proposal=sleep_session.json_proposal,
        applied_at=sleep_session.applied_at,
    )


def _validate_plan_header(plan: dict[str, Any], sleep_session: SleepSession) -> None:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported sleep plan schema_version",
        )
    if str(plan.get("session_id")) != str(sleep_session.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sleep plan session_id does not match URL session",
        )

    input_ids = {str(i) for i in plan.get("input_memory_ids", [])}
    candidate_ids = {str(i) for i in sleep_session.candidate_memory_ids}
    if not input_ids.issubset(candidate_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="input_memory_ids must be a subset of session candidates",
        )
    if not isinstance(plan.get("actions"), list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sleep plan actions must be a list",
        )


async def _apply_create_memory(
    session: AsyncSession,
    user_id: str,
    sleep_session: SleepSession,
    action: dict[str, Any],
) -> tuple[uuid.UUID, str, list[uuid.UUID]]:
    payload = action.get("memory") or {}
    status_value = payload.get("status", "active")
    if status_value != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="created sleep memories must be active",
        )

    scope = payload.get("scope") or {"global": True, "projects": [], "exclude_projects": []}
    scope_projects = await canonicalize_project_scopes(
        session, user_id, scope.get("projects", [])
    )
    scope_exclude = await canonicalize_project_scopes(
        session, user_id, scope.get("exclude_projects", [])
    )
    memory = Memory(
        user_id=user_id,
        title=payload["title"],
        content=payload["content"],
        type=payload["type"],
        layer=payload.get("layer", "L2"),
        priority=payload.get("priority", 5),
        tags=payload.get("tags", []),
        status=status_value,
        source="sleep",
        token_count=count_tokens(payload["content"]),
        scope_global=scope.get("global", True),
        scope_projects=scope_projects,
        scope_exclude=scope_exclude,
        sleep_state="distilled",
        derived_from=[str(i) for i in action.get("derived_from", [])],
    )
    session.add(memory)
    await session.flush()

    edge_ids: list[uuid.UUID] = []
    for source_id in action.get("derived_from", []):
        edge = MemoryEdge(
            user_id=user_id,
            source_memory_id=memory.id,
            target_memory_id=uuid.UUID(str(source_id)),
            relation="derived_from",
            reason="Created by memory sleep consolidation",
            sleep_session_id=sleep_session.id,
        )
        session.add(edge)
        await session.flush()
        edge_ids.append(edge.id)

    return memory.id, f"{memory.title}\n{memory.content}", edge_ids


async def _apply_status_update(
    session: AsyncSession,
    user_id: str,
    sleep_session: SleepSession,
    action: dict[str, Any],
    created_refs: dict[str, uuid.UUID],
) -> tuple[uuid.UUID, uuid.UUID | None]:
    memory = await _get_candidate_memory(session, user_id, action["memory_id"])
    if memory.is_core:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="core memories cannot be changed by sleep apply",
        )
    if memory.status != action.get("from_status"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Memory {memory.id} status changed before apply",
        )

    to_status = action.get("to_status")
    if to_status not in ALLOWED_STATUS_UPDATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sleep status updates can only archive or deprecate memories",
        )

    memory.status = to_status
    memory.sleep_state = "superseded"
    edge_id = None

    superseded_by_ref = action.get("superseded_by_ref")
    if superseded_by_ref:
        target_id = created_refs.get(superseded_by_ref)
        if not target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown superseded_by_ref: {superseded_by_ref}",
            )
        memory.superseded_by = target_id
        edge = MemoryEdge(
            user_id=user_id,
            source_memory_id=memory.id,
            target_memory_id=target_id,
            relation="superseded_by",
            reason=action.get("reason"),
            sleep_session_id=sleep_session.id,
        )
        session.add(edge)
        await session.flush()
        edge_id = edge.id

    return memory.id, edge_id


async def _apply_keep_memory(
    session: AsyncSession,
    user_id: str,
    action: dict[str, Any],
) -> uuid.UUID:
    memory = await _get_candidate_memory(session, user_id, action["memory_id"])
    memory.sleep_state = "reviewed"
    return memory.id


async def _apply_create_edge(
    session: AsyncSession,
    user_id: str,
    sleep_session: SleepSession,
    action: dict[str, Any],
    created_refs: dict[str, uuid.UUID],
) -> uuid.UUID:
    source_id = _resolve_edge_endpoint(action["from"], created_refs)
    target_id = _resolve_edge_endpoint(action["to"], created_refs)
    edge = MemoryEdge(
        user_id=user_id,
        source_memory_id=source_id,
        target_memory_id=target_id,
        relation=action["relation"],
        reason=action.get("reason"),
        sleep_session_id=sleep_session.id,
    )
    session.add(edge)
    await session.flush()
    return edge.id


def _resolve_edge_endpoint(endpoint: dict[str, str], created_refs: dict[str, uuid.UUID]) -> uuid.UUID:
    if endpoint.get("kind") == "client_ref":
        ref_id = endpoint.get("id")
        if ref_id not in created_refs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown edge client_ref: {ref_id}",
            )
        return created_refs[ref_id]
    return uuid.UUID(str(endpoint["id"]))


async def _get_candidate_memory(session: AsyncSession, user_id: str, memory_id: str) -> Memory:
    result = await session.execute(
        select(Memory).where(
            Memory.id == uuid.UUID(str(memory_id)),
            Memory.user_id == user_id,
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory not found: {memory_id}",
        )
    return memory
