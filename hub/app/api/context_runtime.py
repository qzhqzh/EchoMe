"""Unified context retrieval and runtime diagnostics."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from time import perf_counter
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.project_knowledge import project_preflight
from app.core.auth import verify_token
from app.core.config import settings
from app.core.database import async_session_factory, get_session
from app.models.memory import Memory
from app.models.project_knowledge import ContextRun
from app.schemas.context_runtime import UnifiedContextRequest
from app.schemas.project_knowledge import ProjectContextRequest, ProjectPreflightRequest
from app.services.context_compiler import compile_project_context, query_tokens
from app.services.project_identity import resolve_project
from app.services.token_counter import count_tokens

logger = logging.getLogger(__name__)


class RuntimeContractRoute(APIRoute):
    """Apply echome.error.v1 before endpoint dependencies or validation finish."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def contract_handler(request: Request) -> Response:
            request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
            try:
                return await original(request)
            except RequestValidationError as exc:
                error = HTTPException(status_code=422, detail=exc.errors())
                return _runtime_error_response(error, request_id)
            except Exception as exc:
                return _runtime_error_response(exc, request_id)

        return contract_handler


router = APIRouter(
    prefix="/context",
    tags=["context-runtime"],
    route_class=RuntimeContractRoute,
)


def _runtime_route(body: UnifiedContextRequest) -> str:
    if body.mode == "personal" or (body.mode == "auto" and not body.project_hint):
        return "personal"
    if body.mode == "temporal":
        return "temporal"
    if body.mode == "impact" or (body.mode == "auto" and body.changed_paths):
        return "impact"
    return "project"


def _runtime_error_code(exc: Exception) -> str:
    if isinstance(exc, StarletteHTTPException):
        return {
            401: "AUTH_FAILED",
            403: "AUTH_FORBIDDEN",
            404: "PROJECT_NOT_FOUND",
            409: "PROJECT_AMBIGUOUS",
            422: "INVALID_REQUEST",
        }.get(exc.status_code, "HUB_REQUEST_FAILED")
    return "CONTEXT_RUNTIME_FAILED"


def _runtime_error_response(exc: Exception, request_id: str) -> JSONResponse:
    status_code = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = (
        exc.detail
        if isinstance(exc, StarletteHTTPException)
        else str(exc) or exc.__class__.__name__
    )
    if isinstance(detail, str):
        message = detail
    elif isinstance(detail, dict):
        message = str(detail.get("message") or detail)
    else:
        message = str(detail)
    retryable = status_code == 429 or status_code >= 500
    return JSONResponse(
        status_code=status_code,
        content={
            "schema_version": "echome.error.v1",
            "error": {
                "code": _runtime_error_code(exc),
                "message": message,
                "retryable": retryable,
                "request_id": request_id,
                "degraded": status_code >= 500,
                "suggested_action": (
                    "Retry later or use an eligible encrypted read-only cache."
                    if retryable
                    else "Check the project hint, request, and authentication."
                ),
            },
        },
    )


async def _record_failed_context(
    body: UnifiedContextRequest,
    user_id: str,
    request_id: str,
    route: str,
    exc: Exception,
    project_id: str | None = None,
) -> None:
    """Persist a failure outside the request transaction without masking it."""
    try:
        async with async_session_factory() as audit_session:
            run_mode = route if route in {"personal", "impact", "temporal"} else "local"
            audit_session.add(
                ContextRun(
                    user_id=user_id,
                    project_id=project_id,
                    query=body.task,
                    mode=run_mode,
                    changed_paths=body.changed_paths,
                    token_budget=body.token_budget,
                    candidates={},
                    selected={},
                    trace={"failure_stage": route, "project_hint": body.project_hint},
                    status="failed",
                    request_id=request_id,
                    client=body.client,
                    client_version=body.client_version,
                    route=route,
                    error_code=_runtime_error_code(exc),
                )
            )
            await audit_session.commit()
    except Exception:
        logger.exception("Could not persist failed ContextRun %s", request_id)


def _answerability(context: dict[str, Any]) -> str:
    if context.get("conflicts"):
        return "conflicted"
    unknowns = context.get("unknowns") or []
    if unknowns and not any(
        context.get(key) for key in ("constraints", "memories", "evidence", "artifacts")
    ):
        return "insufficient_evidence"
    if unknowns:
        return "partial"
    return "supported"


def _recommended_actions(context: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if context.get("conflicts"):
        actions.append("Inspect the conflicting evidence before acting.")
    if context.get("stale_warnings"):
        actions.append("Verify stale evidence against the current artifact revision.")
    if context.get("unknowns"):
        actions.append("Treat unknowns as unresolved; do not infer missing facts.")
    return actions


async def _personal_context(
    session: AsyncSession,
    body: UnifiedContextRequest,
    user_id: str,
    request_id: str,
) -> dict[str, Any]:
    result = await session.execute(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.status.in_(["active", "ai_review"]),
            Memory.scope_global.is_(True),
        )
    )
    memories = list(result.scalars().all())
    tokens = query_tokens(body.task)
    ranked: list[tuple[float, Memory]] = []
    for memory in memories:
        document_tokens = query_tokens(f"{memory.title} {memory.content} {' '.join(memory.tags)}")
        overlap = len(tokens & document_tokens) / max(1, len(tokens))
        if overlap > 0:
            ranked.append((overlap + memory.priority / 100, memory))
    ranked.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    selected = [item for _, item in ranked[: body.limit]]
    payloads = [
        {
            "id": str(item.id),
            "title": item.title,
            "content": item.content,
            "type": item.type,
            "layer": item.layer,
            "status": item.status,
            "tags": item.tags,
            "updated_at": item.updated_at.isoformat(),
        }
        for item in selected
    ]
    while payloads and count_tokens(str(payloads)) > body.token_budget:
        payloads.pop()
    unknowns = [] if payloads else ["No supported personal memory matched the task."]
    context: dict[str, Any] = {
        "schema_version": "echome.context.v1",
        "scope": "personal",
        "project": None,
        "task": body.task,
        "mode": "personal",
        "constraints": [],
        "memories": payloads,
        "artifacts": [],
        "evidence": [],
        "conflicts": [],
        "stale_warnings": [],
        "unknowns": unknowns,
        "token_budget": body.token_budget,
        "token_used": count_tokens(str(payloads)),
        "retrieval_trace": {
            "strategy": "bounded_lexical",
            "candidate_counts": {"memories": len(memories)},
            "selected_count": len(payloads),
        },
    }
    if body.record_run:
        run = ContextRun(
            user_id=user_id,
            project_id=None,
            query=body.task,
            mode="personal",
            changed_paths=[],
            token_budget=body.token_budget,
            token_used=context["token_used"],
            candidates={"memories": len(memories)},
            selected={"memories": [item["id"] for item in payloads]},
            trace=context["retrieval_trace"],
            request_id=request_id,
            client=body.client,
            client_version=body.client_version,
            route="personal",
        )
        session.add(run)
        await session.flush()
        context["context_run_id"] = str(run.id)
    return context


async def _build_unified_context(
    body: UnifiedContextRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
    audit: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Return one evidence-first context envelope for personal or project work."""
    started = perf_counter()
    request_id = body.request_id or str(uuid.uuid4())
    if body.mode == "personal" or (body.mode == "auto" and not body.project_hint):
        context = await _personal_context(session, body, user_id, request_id)
        route = "personal"
        resolution = None
        preflight = None
    else:
        assert body.project_hint is not None
        resolution_result = await resolve_project(session, user_id, body.project_hint)
        project = resolution_result.project
        if audit is not None:
            audit["project_id"] = project.id
        route = (
            "temporal"
            if body.mode == "temporal"
            else "impact"
            if body.mode == "impact" or (body.mode == "auto" and body.changed_paths)
            else "project"
        )
        compiler_mode = "overview" if route == "temporal" else "impact" if route == "impact" else "local"
        context = await compile_project_context(
            session,
            project,
            ProjectContextRequest(
                project_id=project.id,
                task=body.task,
                changed_paths=body.changed_paths,
                mode=compiler_mode,
                token_budget=body.token_budget,
                limit=body.limit,
                as_of=body.as_of,
                valid_at=body.valid_at,
                record_run=body.record_run,
                request_id=request_id,
                client=body.client,
                client_version=body.client_version,
                route=route,
            ),
            user_id,
        )
        context["schema_version"] = "echome.context.v1"
        context["scope"] = "project"
        resolution = resolution_result.payload(body.project_hint)
        preflight = await project_preflight(
            ProjectPreflightRequest(
                project_id=project.id,
                task=body.task,
                changed_paths=body.changed_paths,
                limit=body.limit,
            ),
            session,
            user_id,
        )
    return {
        **context,
        "preflight": preflight,
        "answerability": _answerability(context),
        "recommended_actions": _recommended_actions(context),
        "resolution": resolution,
        "runtime": {
            "request_id": request_id,
            "route": route,
            "degraded": False,
            "fallback": None,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
        },
    }


@router.post("", response_model=None)
async def get_unified_context(
    body: UnifiedContextRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any] | JSONResponse:
    """Return one evidence-first context envelope and audit failed attempts."""
    request_id = body.request_id or str(uuid.uuid4())
    body.request_id = request_id
    route = _runtime_route(body)
    audit: dict[str, str | None] = {"project_id": None}
    try:
        return await _build_unified_context(body, session, user_id, audit)
    except Exception as exc:
        await session.rollback()
        await _record_failed_context(
            body,
            user_id,
            request_id,
            route,
            exc,
            audit["project_id"],
        )
        return _runtime_error_response(exc, request_id)


@router.get("/runtime/health")
async def runtime_health(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """Check authenticated Hub, database, migration, and embedding dependencies."""
    del user_id
    database = "ok"
    migration_revision = None
    try:
        await session.execute(text("SELECT 1"))
        migration_revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception:
        await session.rollback()
        database = "unavailable"
    embedding = "unavailable"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.embedding_url}/health")
            embedding = "ok" if response.is_success else "degraded"
    except httpx.HTTPError:
        pass
    return {
        "status": "ok" if database == "ok" else "degraded",
        "hub_version": settings.app_version,
        "schema_version": migration_revision,
        "feature_flags": {
            "context_compiler": settings.context_compiler_enabled,
            "project_automation": settings.project_automation_enabled,
            "unified_context": True,
        },
        "components": {
            "token": "ok",
            "hub": "ok",
            "database": database,
            "embedding": embedding,
        },
    }
