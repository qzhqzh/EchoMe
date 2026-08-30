"""Memory Sleep API routes."""

import json
import uuid
from copy import deepcopy
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
    ELIGIBLE_CANDIDATE_STATUSES,
    SleepApplyRequest,
    SleepApplyResponse,
    SleepCandidatesRequest,
    SleepCandidatesResponse,
    SleepEdgeItem,
    SleepMemoryItem,
    SleepProposalSubmitRequest,
    SleepSessionResponse,
)
from app.services.content_safety import require_safe_content
from app.services.memory_sleep_simulation import simulate_sleep_plan_v2
from app.services.project_identity import (
    canonicalize_project_scopes,
    project_scope_ids,
)
from app.services.token_counter import count_tokens

router = APIRouter(prefix="/memory-sleep", tags=["memory-sleep"])

PLAN_SCHEMA_V1 = "memory_sleep_plan.v1"
PLAN_SCHEMA_V2 = "memory_sleep_plan.v2"
PLAN_SCHEMA_VERSION = PLAN_SCHEMA_V2
SUPPORTED_PLAN_SCHEMAS = {PLAN_SCHEMA_V1, PLAN_SCHEMA_V2}
ORGANIZED_STATES = {"reviewed", "distilled", "superseded"}
ALLOWED_STATUS_UPDATES = {"archived", "deprecated"}
ALLOWED_ACTIONS = {
    "create_memory",
    "update_memory_status",
    "create_edge",
    "keep_memory",
    "needs_human",
}
ALLOWED_MEMORY_TYPES = {
    "identity",
    "guardrail",
    "reasoning",
    "method",
    "stack",
    "style",
    "decision",
    "context",
    "template",
    "project",
}
ALLOWED_EDGE_RELATIONS = {
    "derived_from",
    "supersedes",
    "superseded_by",
    "duplicates",
    "conflicts_with",
    "specializes",
    "related_to",
}


def _plan_json_schema(schema_version: str = PLAN_SCHEMA_VERSION) -> dict[str, Any]:
    """Return the minimal JSON plan contract clients must submit."""
    required = ["schema_version", "session_id", "input_memory_ids", "actions"]
    schema: dict[str, Any] = {
        "schema_version": schema_version,
        "required": required,
        "actions": sorted(ALLOWED_ACTIONS),
    }
    if schema_version == PLAN_SCHEMA_V2:
        required.extend(["preconditions", "replay_cases"])
        schema.update(
            {
                "preconditions": {
                    "one_per_input_memory": True,
                    "required": ["memory_id", "status", "sleep_state", "updated_at"],
                },
                "replay_cases": {
                    "min_items": 1,
                    "required": ["case_id", "query", "expected_memory_ids", "top_k"],
                },
                "quality_gates": {
                    "min_source_coverage": 1.0,
                    "max_replay_regressions": 0,
                    "max_token_growth_ratio": 0.1,
                    "min_scored_replay_cases": 1,
                },
                "server_simulation": "server-owned; client values are replaced",
            }
        )
    return schema


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
    eligible_statuses = [item for item in body.status if item in ELIGIBLE_CANDIDATE_STATUSES]
    query = query.where(
        Memory.user_id == user_id,
        Memory.status.in_(eligible_statuses),
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
        canonical = await canonicalize_project_scopes(session, user_id, [body.project_id])
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
        sleep_session = await _get_sleep_session(session, body.session_id, user_id, lock=True)
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
        schema_version=body.plan_schema_version,
        supported_schema_versions=sorted(SUPPORTED_PLAN_SCHEMAS),
        candidates=[_memory_item(m) for m in page],
        protected_memories=[_memory_item(m, _protection_reason(m)) for m in protected]
        if body.include_protected
        else [],
        relation_edges=[_edge_item(e) for e in edges],
        json_schema=_plan_json_schema(body.plan_schema_version),
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
    sleep_session = await _get_sleep_session(session, session_id, user_id, lock=True)
    if sleep_session.status in {"applied", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update a finalized sleep session",
        )

    plan = deepcopy(body.json_proposal)
    _validate_plan_header(plan, sleep_session)
    require_safe_content(body.text_proposal, json.dumps(plan, default=str))
    if plan["schema_version"] == PLAN_SCHEMA_V2:
        simulation = await _simulate_v2_plan(session, user_id, sleep_session, plan, lock=False)
        if not simulation["passed"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Sleep v2 simulation did not pass; proposal was not saved",
                    "simulation": simulation,
                },
            )
        plan["server_simulation"] = simulation
    sleep_session.text_proposal = body.text_proposal
    sleep_session.json_proposal = plan
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
    sleep_session = await _get_sleep_session(session, session_id, user_id, lock=True)
    if sleep_session.status == "applied":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sleep session is already applied",
        )
    if sleep_session.status not in {"proposed", "approved"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sleep session cannot be applied from status {sleep_session.status}",
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
    if plan["schema_version"] == PLAN_SCHEMA_V2:
        simulation = await _simulate_v2_plan(session, user_id, sleep_session, plan, lock=True)
        if not simulation["passed"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Sleep v2 simulation did not pass; source data was not changed",
                    "simulation": simulation,
                },
            )

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
    session: AsyncSession,
    session_id: uuid.UUID,
    user_id: str,
    *,
    lock: bool = False,
) -> SleepSession:
    query = select(SleepSession).where(
        SleepSession.id == session_id,
        SleepSession.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    result = await session.execute(query)
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
    if plan.get("schema_version") not in SUPPORTED_PLAN_SCHEMAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported sleep plan schema_version",
        )
    if str(plan.get("session_id")) != str(sleep_session.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sleep plan session_id does not match URL session",
        )

    raw_input_ids = plan.get("input_memory_ids")
    if not isinstance(raw_input_ids, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sleep plan input_memory_ids must be a list",
        )
    input_ids = {_validated_uuid(item, "input_memory_ids") for item in raw_input_ids}
    if len(input_ids) != len(raw_input_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sleep plan input_memory_ids must be unique",
        )
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
    _validate_common_actions(plan, sleep_session)
    if plan["schema_version"] == PLAN_SCHEMA_V2:
        _validate_v2_plan(plan, sleep_session)


def _validated_uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} contains an invalid memory UUID",
        ) from exc


def _validated_id_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must be a list",
        )
    return [_validated_uuid(item, field) for item in value]


def _validate_created_memory(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid create_memory action")
    if not all(
        isinstance(payload.get(key), str) and payload[key] for key in ("title", "content", "type")
    ):
        raise HTTPException(status_code=400, detail="create_memory payload is incomplete")
    require_safe_content(payload["title"], payload["content"])
    if len(payload["title"]) > 256 or len(payload["content"]) > 100_000:
        raise HTTPException(status_code=400, detail="Created memory content is too large")
    if payload["type"] not in ALLOWED_MEMORY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid created memory type")
    if payload.get("layer", "L2") not in {"L0", "L1", "L2"}:
        raise HTTPException(status_code=400, detail="Invalid created memory layer")
    priority = payload.get("priority", 5)
    if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 10:
        raise HTTPException(status_code=400, detail="Invalid created memory priority")
    if payload.get("status", "active") != "active":
        raise HTTPException(status_code=400, detail="Created sleep memories must be active")
    tags = payload.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > 20
        or any(not isinstance(tag, str) for tag in tags)
    ):
        raise HTTPException(status_code=400, detail="Invalid created memory tags")
    scope = payload.get("scope") or {
        "global": True,
        "projects": [],
        "exclude_projects": [],
    }
    if (
        not isinstance(scope, dict)
        or not isinstance(scope.get("global", True), bool)
        or not isinstance(scope.get("projects", []), list)
        or not isinstance(scope.get("exclude_projects", []), list)
        or any(not isinstance(item, str) for item in scope.get("projects", []))
        or any(not isinstance(item, str) for item in scope.get("exclude_projects", []))
    ):
        raise HTTPException(status_code=400, detail="Invalid created memory scope")
    if payload["type"] == "project" and not scope.get("projects"):
        raise HTTPException(
            status_code=400, detail="Created project memories require project scope"
        )


def _validate_common_actions(plan: dict[str, Any], sleep_session: SleepSession) -> None:
    input_ids = {_validated_uuid(item, "input_memory_ids") for item in plan["input_memory_ids"]}
    candidate_ids = {str(item) for item in sleep_session.candidate_memory_ids}
    create_refs: set[str] = set()
    for action in plan["actions"]:
        if not isinstance(action, dict) or action.get("op") not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=400, detail="Sleep plan contains an invalid action")
        if action["op"] == "create_memory":
            ref = action.get("client_ref")
            if not isinstance(ref, str) or not ref or ref in create_refs:
                raise HTTPException(status_code=400, detail="Invalid create_memory client_ref")
            create_refs.add(ref)

    for action in plan["actions"]:
        op = action["op"]
        if op == "create_memory":
            _validate_created_memory(action.get("memory"))
            derived = set(_validated_id_list(action.get("derived_from"), "derived_from"))
            if not derived or not derived.issubset(input_ids):
                raise HTTPException(
                    status_code=400,
                    detail="create_memory derived_from must reference input memories",
                )
        elif op in {"keep_memory", "update_memory_status"}:
            memory_id = _validated_uuid(action.get("memory_id"), f"{op}.memory_id")
            if memory_id not in input_ids:
                raise HTTPException(
                    status_code=400, detail=f"Action references non-input {memory_id}"
                )
            if op == "update_memory_status":
                if action.get("to_status") not in ALLOWED_STATUS_UPDATES:
                    raise HTTPException(status_code=400, detail="Invalid sleep status update")
                if not isinstance(action.get("from_status"), str) or not action["from_status"]:
                    raise HTTPException(
                        status_code=400, detail="Sleep status update needs from_status"
                    )
                ref = action.get("superseded_by_ref")
                if ref is not None and ref not in create_refs:
                    raise HTTPException(status_code=400, detail="Unknown superseded_by_ref")
        elif op == "needs_human":
            raw_ids = action.get("memory_ids")
            if raw_ids is None:
                raw_ids = [action.get("memory_id")]
            memory_ids = set(_validated_id_list(raw_ids, "needs_human.memory_ids"))
            if not memory_ids or not memory_ids.issubset(input_ids):
                raise HTTPException(status_code=400, detail="Invalid needs_human action")
        elif op == "create_edge":
            if action.get("relation") not in ALLOWED_EDGE_RELATIONS:
                raise HTTPException(status_code=400, detail="Invalid sleep edge relation")
            for endpoint in (action.get("from"), action.get("to")):
                if not isinstance(endpoint, dict) or endpoint.get("kind") not in {
                    "memory",
                    "client_ref",
                }:
                    raise HTTPException(status_code=400, detail="Invalid sleep edge endpoint")
                endpoint_id = endpoint.get("id")
                if endpoint["kind"] == "client_ref":
                    if endpoint_id not in create_refs:
                        raise HTTPException(status_code=400, detail="Unknown sleep edge client_ref")
                elif _validated_uuid(endpoint_id, "create_edge endpoint") not in candidate_ids:
                    raise HTTPException(
                        status_code=400,
                        detail="Sleep edge must reference a session candidate",
                    )


def _validate_v2_plan(plan: dict[str, Any], sleep_session: SleepSession) -> None:
    input_ids = {str(item) for item in plan.get("input_memory_ids", [])}
    if not input_ids:
        raise HTTPException(status_code=400, detail="Sleep v2 requires input_memory_ids")

    preconditions = plan.get("preconditions")
    if not isinstance(preconditions, list):
        raise HTTPException(status_code=400, detail="Sleep v2 requires preconditions")
    precondition_ids = {
        str(item.get("memory_id"))
        for item in preconditions
        if isinstance(item, dict) and item.get("memory_id")
    }
    if precondition_ids != input_ids or len(preconditions) != len(input_ids):
        raise HTTPException(
            status_code=400,
            detail="Sleep v2 preconditions must cover every input memory exactly once",
        )
    if any(
        not isinstance(item, dict)
        or not all(item.get(key) is not None for key in ("status", "sleep_state", "updated_at"))
        for item in preconditions
    ):
        raise HTTPException(status_code=400, detail="Sleep v2 preconditions are incomplete")

    candidate_ids = {str(item) for item in sleep_session.candidate_memory_ids}
    terminal_ids: list[str] = []
    create_actions: dict[str, dict[str, Any]] = {}
    status_actions: list[dict[str, Any]] = []
    for action in plan["actions"]:
        if not isinstance(action, dict) or action.get("op") not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=400, detail="Sleep v2 contains an invalid action")
        op = action["op"]
        if op == "create_memory":
            ref = action.get("client_ref")
            payload = action.get("memory")
            derived = {str(item) for item in action.get("derived_from", [])}
            if not ref or ref in create_actions or not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Invalid create_memory action")
            if not all(payload.get(key) for key in ("title", "content", "type")):
                raise HTTPException(status_code=400, detail="create_memory payload is incomplete")
            if len(str(payload["title"])) > 256 or len(str(payload["content"])) > 100_000:
                raise HTTPException(status_code=400, detail="Created memory content is too large")
            if payload["type"] not in ALLOWED_MEMORY_TYPES:
                raise HTTPException(status_code=400, detail="Invalid created memory type")
            if payload.get("layer", "L2") not in {"L0", "L1", "L2"}:
                raise HTTPException(status_code=400, detail="Invalid created memory layer")
            priority = payload.get("priority", 5)
            if (
                not isinstance(priority, int)
                or isinstance(priority, bool)
                or not 1 <= priority <= 10
            ):
                raise HTTPException(status_code=400, detail="Invalid created memory priority")
            if payload.get("status", "active") != "active":
                raise HTTPException(
                    status_code=400, detail="Created Sleep v2 memories must be active"
                )
            if not isinstance(payload.get("tags", []), list):
                raise HTTPException(status_code=400, detail="Invalid created memory tags")
            if len(payload.get("tags", [])) > 20:
                raise HTTPException(status_code=400, detail="Created memory has too many tags")
            scope = payload.get("scope") or {
                "global": True,
                "projects": [],
                "exclude_projects": [],
            }
            if (
                not isinstance(scope, dict)
                or not isinstance(scope.get("global", True), bool)
                or not isinstance(scope.get("projects", []), list)
                or not isinstance(scope.get("exclude_projects", []), list)
            ):
                raise HTTPException(status_code=400, detail="Invalid created memory scope")
            if payload["type"] == "project" and not scope.get("projects"):
                raise HTTPException(
                    status_code=400,
                    detail="Created project memories require project scope",
                )
            if not derived or not derived.issubset(input_ids):
                raise HTTPException(
                    status_code=400,
                    detail="create_memory derived_from must reference input memories",
                )
            create_actions[str(ref)] = action
        elif op in {"keep_memory", "update_memory_status"}:
            memory_id = str(action.get("memory_id"))
            if memory_id not in input_ids:
                raise HTTPException(
                    status_code=400, detail=f"Action references non-input {memory_id}"
                )
            terminal_ids.append(memory_id)
            if op == "update_memory_status":
                if action.get("to_status") not in ALLOWED_STATUS_UPDATES:
                    raise HTTPException(status_code=400, detail="Invalid Sleep v2 status update")
                if not action.get("from_status"):
                    raise HTTPException(
                        status_code=400, detail="Sleep v2 status update needs from_status"
                    )
                status_actions.append(action)
        elif op == "needs_human":
            memory_ids = action.get("memory_ids") or [action.get("memory_id")]
            normalized = {str(item) for item in memory_ids if item}
            if not normalized or not normalized.issubset(input_ids):
                raise HTTPException(status_code=400, detail="Invalid needs_human action")
            terminal_ids.extend(normalized)
        elif op == "create_edge":
            if action.get("relation") not in ALLOWED_EDGE_RELATIONS:
                raise HTTPException(status_code=400, detail="Invalid Sleep v2 edge relation")

    if len(terminal_ids) != len(set(terminal_ids)) or set(terminal_ids) != input_ids:
        raise HTTPException(
            status_code=400,
            detail="Sleep v2 requires exactly one terminal action per input memory",
        )
    for action in status_actions:
        if action["to_status"] != "archived":
            continue
        ref = str(action.get("superseded_by_ref") or "")
        replacement = create_actions.get(ref)
        if replacement is None or str(action["memory_id"]) not in {
            str(item) for item in replacement.get("derived_from", [])
        }:
            raise HTTPException(
                status_code=400,
                detail="Archived Sleep v2 memories require a derived replacement",
            )

    replay_cases = plan.get("replay_cases")
    if not isinstance(replay_cases, list) or not replay_cases:
        raise HTTPException(status_code=400, detail="Sleep v2 requires replay_cases")
    replay_ids: list[str] = []
    for case in replay_cases:
        if not isinstance(case, dict) or not case.get("case_id") or not case.get("query"):
            raise HTTPException(status_code=400, detail="Invalid Sleep v2 replay case")
        expected_ids = set(
            _validated_id_list(case.get("expected_memory_ids"), "expected_memory_ids")
        )
        if not expected_ids or not expected_ids.issubset(candidate_ids):
            raise HTTPException(status_code=400, detail="Replay expectations must be candidates")
        if (
            not isinstance(case.get("top_k"), int)
            or isinstance(case["top_k"], bool)
            or not 1 <= case["top_k"] <= 100
        ):
            raise HTTPException(status_code=400, detail="Replay top_k must be between 1 and 100")
        replay_ids.append(str(case["case_id"]))
    if len(replay_ids) != len(set(replay_ids)):
        raise HTTPException(status_code=400, detail="Replay case IDs must be unique")

    gates = plan.get("quality_gates", {})
    gate_ranges = {
        "min_source_coverage": (1.0, 1.0),
        "max_replay_regressions": (0, 0),
        "max_token_growth_ratio": (0.0, 0.1),
        "min_scored_replay_cases": (1, 1000),
    }
    if not isinstance(gates, dict):
        raise HTTPException(status_code=400, detail="quality_gates must be an object")
    for key, value in gates.items():
        if key not in gate_ranges or isinstance(value, bool) or not isinstance(value, int | float):
            raise HTTPException(status_code=400, detail=f"Invalid quality gate: {key}")
        lower, upper = gate_ranges[key]
        if not lower <= value <= upper:
            raise HTTPException(status_code=400, detail=f"Quality gate out of range: {key}")

    for action in plan["actions"]:
        if action["op"] != "create_edge":
            continue
        for endpoint in (action.get("from"), action.get("to")):
            if not isinstance(endpoint, dict) or not endpoint.get("id"):
                raise HTTPException(status_code=400, detail="Invalid Sleep v2 edge endpoint")
            endpoint_id = str(endpoint["id"])
            if endpoint.get("kind") == "client_ref":
                if endpoint_id not in create_actions:
                    raise HTTPException(status_code=400, detail="Unknown Sleep v2 edge client_ref")
            elif endpoint_id not in candidate_ids:
                raise HTTPException(
                    status_code=400, detail="Sleep v2 edge must reference a candidate"
                )


async def _simulate_v2_plan(
    session: AsyncSession,
    user_id: str,
    sleep_session: SleepSession,
    plan: dict[str, Any],
    *,
    lock: bool,
) -> dict[str, Any]:
    candidate_ids = [uuid.UUID(str(item)) for item in sleep_session.candidate_memory_ids]
    query = select(Memory).where(Memory.user_id == user_id, Memory.id.in_(candidate_ids))
    if lock:
        query = query.with_for_update()
    result = await session.execute(query)
    return simulate_sleep_plan_v2(list(result.scalars().all()), plan)


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
    scope_projects = await canonicalize_project_scopes(session, user_id, scope.get("projects", []))
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


def _resolve_edge_endpoint(
    endpoint: dict[str, str], created_refs: dict[str, uuid.UUID]
) -> uuid.UUID:
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
