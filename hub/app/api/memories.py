"""Memory CRUD and search API routes."""

import json
import uuid
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.core.ratelimit import RATE_SEARCH, RATE_WRITE, limiter
from app.models.memory import Memory
from app.schemas.memory import (
    MemoryCreate,
    MemoryCreateResponse,
    MemoryListResponse,
    MemoryPatch,
    MemoryResponse,
    MemorySearchRequest,
    MemoryUpdate,
    SearchResponse,
    SearchResultItem,
)
from app.services.content_safety import require_safe_content
from app.services.embedding import get_embedding
from app.services.memory_retrieval import memory_query_tokens, retrieve_memories
from app.services.project_identity import (
    canonicalize_project_scopes,
    project_scope_ids,
    resolve_project,
)
from app.services.token_counter import count_tokens

router = APIRouter(prefix="/memories", tags=["memories"])


async def _query_project_scope_ids(
    session: AsyncSession, user_id: str, project_hint: str
) -> list[str]:
    """Expand active aliases while preserving the old unknown-project empty result."""
    try:
        project = (await resolve_project(session, user_id, project_hint)).project
    except HTTPException as exc:
        if exc.status_code == 404:
            return [project_hint]
        raise
    return await project_scope_ids(session, user_id, project.id)


_query_tokens = memory_query_tokens


async def _compute_and_store_embedding(memory_id: uuid.UUID, text: str) -> None:
    """Background task: compute embedding and store it.

    Uses a targeted UPDATE statement to only modify the embedding column,
    avoiding race conditions where loading the full ORM object could
    overwrite concurrent changes (e.g. layer updates from PUT/PATCH).

    IMPORTANT: This function MUST NOT raise exceptions — background task errors
    must never propagate to the ASGI handler, as that would cause the main
    request's session commit to be rolled back.

    The route handlers commit before scheduling this task, so the task never
    waits on a row lock held by the request transaction.
    """
    import logging

    from sqlalchemy import update as sql_update

    from app.core.database import async_session_factory

    logger = logging.getLogger("embedding_task")

    logger.info(f"Background task started for memory {memory_id}")

    try:
        embedding = await get_embedding(text)
        if embedding is None:
            return

        async with async_session_factory() as session:
            result = await session.execute(
                sql_update(Memory).where(Memory.id == memory_id).values(embedding=embedding)
            )
            if cast(Any, result).rowcount > 0:
                await session.commit()
                logger.info(f"Stored embedding for memory {memory_id}")
            else:
                logger.info(f"Memory not found while storing embedding: {memory_id}")
    except Exception as e:
        # Log but never raise — background task failures must not affect the main request
        logger.warning(f"Failed to compute/store embedding for {memory_id}: {e}")


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    type: str | None = None,
    layer: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    tags: str | None = None,
    project_id: str | None = None,
    search_query: str | None = Query(None, alias="query"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> MemoryListResponse:
    """List memories with optional filters."""
    query = select(Memory).where(Memory.user_id == user_id)

    if type:
        query = query.where(Memory.type == type)
    if layer:
        query = query.where(Memory.layer == layer)
    if status_filter:
        query = query.where(Memory.status == status_filter)
    else:
        query = query.where(Memory.status.in_(["active", "ai_review"]))
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        for tag in tag_list:
            query = query.where(Memory.tags.contains([tag]))
    if project_id:
        scope_ids = await _query_project_scope_ids(session, user_id, project_id)
        query = query.where(
            or_(*(Memory.scope_projects.contains([scope_id]) for scope_id in scope_ids))
        )
    relevance: Any = None
    if isinstance(search_query, str) and search_query:
        title_field = func.lower(Memory.title)
        content_field = func.lower(Memory.content)
        tags_field = func.lower(Memory.tags.cast(String))
        search_fields = (title_field, content_field, tags_field)
        patterns = [f"%{search_query.lower()}%"]
        patterns.extend(f"%{token}%" for token in _query_tokens(search_query))
        query = query.where(
            or_(
                *[
                    field.like(pattern)
                    for pattern in patterns
                    for field in search_fields
                ]
            )
        )
        relevance = sum(
            case((title_field.like(pattern), 5), else_=0)
            + case((tags_field.like(pattern), 4), else_=0)
            + case((content_field.like(pattern), 1), else_=0)
            for pattern in patterns
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # Fetch page
    if relevance is not None:
        query = query.order_by(relevance.desc(), Memory.priority.desc(), Memory.updated_at.desc())
    else:
        query = query.order_by(Memory.updated_at.desc())
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    memories = result.scalars().all()

    return MemoryListResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=memories,
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Memory:
    """Get a single memory by ID."""
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return memory


@router.post("", response_model=MemoryCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_WRITE)
async def create_memory(
    request: Request,
    body: MemoryCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Memory:
    """Create a new memory."""
    require_safe_content(json.dumps(body.model_dump(mode="json"), ensure_ascii=False))
    # Validate: project type must have project association
    memory_type = body.type.value
    if memory_type == "project" and not body.scope.projects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project type memory must be associated with a project",
        )

    token_count = count_tokens(body.content)
    scope_projects = await canonicalize_project_scopes(
        session, user_id, body.scope.projects
    )
    scope_exclude = await canonicalize_project_scopes(
        session, user_id, body.scope.exclude_projects
    )

    memory = Memory(
        user_id=user_id,
        title=body.title,
        content=body.content,
        type=body.type.value,
        layer=body.layer.value,
        priority=body.priority,
        tags=body.tags,
        status=body.status.value,
        scope_global=body.scope.global_,
        scope_projects=scope_projects,
        scope_exclude=scope_exclude,
        source=body.source.value,
        token_count=token_count,
        visibility=body.visibility.value,
    )
    session.add(memory)
    await session.flush()
    await session.commit()

    # Compute embedding in background (non-blocking)
    embed_text = f"{body.title}\n{body.content}"
    background_tasks.add_task(_compute_and_store_embedding, memory.id, embed_text)

    return memory


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Memory:
    """Full update of a memory."""
    require_safe_content(json.dumps(body.model_dump(mode="json"), ensure_ascii=False))
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    # Validate: project type must have project association
    memory_type = body.type.value
    if memory_type == "project" and not body.scope.projects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project type memory must be associated with a project",
        )

    scope_projects = await canonicalize_project_scopes(
        session, user_id, body.scope.projects
    )
    scope_exclude = await canonicalize_project_scopes(
        session, user_id, body.scope.exclude_projects
    )

    memory.title = body.title
    memory.content = body.content
    memory.type = body.type.value
    memory.layer = body.layer.value
    memory.priority = body.priority
    memory.tags = body.tags
    memory.status = body.status.value
    memory.scope_global = body.scope.global_
    memory.scope_projects = scope_projects
    memory.scope_exclude = scope_exclude
    memory.source = body.source.value
    memory.token_count = count_tokens(body.content)
    memory.visibility = body.visibility.value

    # Recompute embedding after the request transaction has committed.
    embed_text = f"{body.title}\n{body.content}"

    # Flush to ensure changes are persisted before response serialization
    await session.flush()
    await session.commit()

    background_tasks.add_task(_compute_and_store_embedding, memory.id, embed_text)

    return memory


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def patch_memory(
    memory_id: uuid.UUID,
    body: MemoryPatch,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Memory:
    """Partial update of a memory."""
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    update_data = body.model_dump(exclude_unset=True)
    require_safe_content(json.dumps(update_data, ensure_ascii=False, default=str))
    if "scope" in update_data and update_data["scope"] is not None:
        scope = update_data.pop("scope")
        memory.scope_global = scope.get("global", memory.scope_global)
        memory.scope_projects = await canonicalize_project_scopes(
            session, user_id, scope.get("projects", memory.scope_projects)
        )
        memory.scope_exclude = await canonicalize_project_scopes(
            session, user_id, scope.get("exclude_projects", memory.scope_exclude)
        )

    for field, value in update_data.items():
        if value is not None:
            if field in ("type", "layer", "status", "source", "visibility"):
                setattr(memory, field, value.value if hasattr(value, "value") else value)
            else:
                setattr(memory, field, value)

    if "content" in update_data and update_data["content"]:
        memory.token_count = count_tokens(memory.content)

    embed_text = None
    if "title" in update_data or "content" in update_data:
        embed_text = f"{memory.title}\n{memory.content}"

    # Flush to ensure changes are persisted before response serialization
    await session.flush()
    await session.commit()

    if embed_text is not None:
        background_tasks.add_task(_compute_and_store_embedding, memory.id, embed_text)

    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    hard: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> None:
    """Delete a memory (soft delete by default)."""
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    if hard:
        await session.delete(memory)
    else:
        memory.status = "archived"


@router.post("/search", response_model=SearchResponse)
@limiter.limit(RATE_SEARCH)
async def search_memories(
    request: Request,
    body: MemorySearchRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> SearchResponse:
    """Search memories using hybrid: vector similarity + keyword matching."""
    scope_ids = None
    if body.project_id:
        scope_ids = await _query_project_scope_ids(session, user_id, body.project_id)
    retrieval = await retrieve_memories(
        session,
        user_id=user_id,
        query=body.query,
        limit=body.top_k,
        min_source_score=body.min_score,
        memory_type=body.type.value if body.type else None,
        layer=body.layer.value if body.layer else None,
        tags=body.tags,
        project_scope_ids=scope_ids,
    )

    return SearchResponse(
        results=[
            SearchResultItem(
                id=item.memory.id,
                title=item.memory.title,
                content=item.memory.content,
                type=item.memory.type,
                layer=item.memory.layer,
                score=round(item.score, 3),
                tags=item.memory.tags,
            )
            for item in retrieval.items
        ],
        total_searched=retrieval.total_candidates,
    )
