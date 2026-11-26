"""Bounded project-aware discovery without compiling or recording a context run."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.context_runtime import ContextDiscoveryRequest
from app.services.context_policy import apply_context_policy
from app.services.discovery_query import explicit_recall_requested
from app.services.memory_retrieval import retrieve_memories
from app.services.project_identity import ProjectResolution, project_scope_ids, resolve_project


async def _resolve_scope(
    session: AsyncSession, user_id: str, hints: list[str],
) -> tuple[ProjectResolution | None, str]:
    """Use registered identities only; a missing hint does not override a known one."""
    resolutions: dict[str, ProjectResolution] = {}
    for hint in dict.fromkeys(value.strip() for value in hints if value.strip()):
        try:
            result = await resolve_project(session, user_id, hint)
        except HTTPException as exc:
            if exc.status_code == 409:
                return None, "ambiguous"
            if exc.status_code == 404:
                continue
            raise
        resolutions[result.project.id] = result
    if len(resolutions) > 1:
        return None, "ambiguous"
    return (next(iter(resolutions.values())), "resolved") if resolutions else (None, "not_found")


async def build_discovery(
    session: AsyncSession, body: ContextDiscoveryRequest, user_id: str,
) -> dict[str, Any]:
    hints = ([body.project_hint] if body.project_hint else []) + body.project_hints
    resolution, status = await _resolve_scope(session, user_id, hints)
    project = resolution.project if resolution else None
    scope_ids = await project_scope_ids(session, user_id, project.id) if project else None
    retrieval = await retrieve_memories(
        session, user_id=user_id, query=body.task, limit=body.limit,
        global_only=project is None, project_scope_ids=scope_ids,
        embedding_timeout_seconds=1.2, discovery=not explicit_recall_requested(body.task),
    )
    # Policy remains a read-only annotation. Never turn discovery into a new
    # source mutation, completion contract, or silent exclusion of hard rules.
    policy_context: dict[str, Any] = {
        "memories": [
            {
                "id": str(item.memory.id), "title": item.memory.title,
                "content": item.memory.content, "type": item.memory.type,
                "layer": item.memory.layer, "status": item.memory.status,
                "tags": item.memory.tags,
                "updated_at": item.memory.updated_at.isoformat(),
            }
            for item in retrieval.items
        ],
        "constraints": [], "task": body.task,
    }
    await apply_context_policy(
        session, user_id=user_id, context=policy_context, requested_mode="shadow",
        enforce_enabled=False, persist_assessments=False, query_mode="personal",
    )
    references = []
    for item in policy_context["memories"]:
        reference: dict[str, Any] = {
            "id": item["id"], "title": item["title"], "needs_expansion": True,
            "tool": "echome_get",
        }
        if item.get("intervention"):
            reference["intervention"] = item["intervention"]
        if item.get("warning"):
            reference["warning"] = item["warning"]
        references.append(reference)
    result: dict[str, Any] = {
        "schema_version": "echome.context.v1", "view": "discovery",
        "scope": "project" if project else "personal",
        "project": {"id": project.id, "name": project.name} if project else None,
        "project_resolution": {
            "status": status, "auto_resolved": project is not None,
            "canonical_project_id": project.id if project else None,
            "project_context_available": project is not None,
            "requires_confirmation": False,
        },
        "memory_index": references, "knowledge_refs": [],
        "notice": (
            "Candidate references only; expand applicable entries before relying on them. "
            "This is not a complete context or constraint pack. Empty results do not prove "
            "there is no useful history; explicit search remains available."
        ),
        "retrieval_trace": retrieval.trace,
    }
    if project:
        result["project_reference"] = {
            "needs_expansion": True, "tool": "echome_context",
            "read": {
                "tool": "echome_context",
                "arguments": {"project_hint": project.id, "mode": "project"},
            },
            "notice": "Add the current task when retrieving complete project constraints.",
        }
    return result
