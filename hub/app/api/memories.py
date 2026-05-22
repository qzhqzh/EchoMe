"""Memory CRUD and search API routes."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
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
from app.services.embedding import get_embedding
from app.services.token_counter import count_tokens

router = APIRouter(prefix="/memories", tags=["memories"])


async def _compute_and_store_embedding(memory_id: uuid.UUID, text: str) -> None:
    """Background task: compute embedding and store it."""
    from app.core.database import async_session_factory

    embedding = await get_embedding(text)
    if embedding is None:
        return

    async with async_session_factory() as session:
        result = await session.execute(select(Memory).where(Memory.id == memory_id))
        memory = result.scalar_one_or_none()
        if memory:
            memory.embedding = embedding
            await session.commit()


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    type: str | None = None,
    layer: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    tags: str | None = None,
    project_id: str | None = None,
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
        query = query.where(Memory.status == "active")
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        for tag in tag_list:
            query = query.where(Memory.tags.contains([tag]))
    if project_id:
        query = query.where(Memory.scope_projects.contains([project_id]))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # Fetch page
    query = query.order_by(Memory.priority.desc(), Memory.updated_at.desc())
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    memories = result.scalars().all()

    return MemoryListResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=memories,  # type: ignore[arg-type]
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
    token_count = count_tokens(body.content)

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
        scope_projects=body.scope.projects,
        scope_exclude=body.scope.exclude_projects,
        source=body.source.value,
        token_count=token_count,
        visibility=body.visibility.value,
    )
    session.add(memory)
    await session.flush()

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
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    memory.title = body.title
    memory.content = body.content
    memory.type = body.type.value
    memory.layer = body.layer.value
    memory.priority = body.priority
    memory.tags = body.tags
    memory.status = body.status.value
    memory.scope_global = body.scope.global_
    memory.scope_projects = body.scope.projects
    memory.scope_exclude = body.scope.exclude_projects
    memory.source = body.source.value
    memory.token_count = count_tokens(body.content)
    memory.visibility = body.visibility.value

    # Recompute embedding on content change
    embed_text = f"{body.title}\n{body.content}"
    background_tasks.add_task(_compute_and_store_embedding, memory.id, embed_text)

    # Flush to ensure changes are persisted before response serialization
    await session.flush()

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
    if "scope" in update_data and update_data["scope"] is not None:
        scope = update_data.pop("scope")
        memory.scope_global = scope.get("global", memory.scope_global)
        memory.scope_projects = scope.get("projects", memory.scope_projects)
        memory.scope_exclude = scope.get("exclude_projects", memory.scope_exclude)

    for field, value in update_data.items():
        if value is not None:
            if field in ("type", "layer", "status", "source", "visibility"):
                setattr(memory, field, value.value if hasattr(value, "value") else value)
            else:
                setattr(memory, field, value)

    if "content" in update_data and update_data["content"]:
        memory.token_count = count_tokens(memory.content)

    # Recompute embedding if title or content changed
    if "title" in update_data or "content" in update_data:
        embed_text = f"{memory.title}\n{memory.content}"
        background_tasks.add_task(_compute_and_store_embedding, memory.id, embed_text)

    # Flush to ensure changes are persisted before response serialization
    await session.flush()

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
    from pgvector.sqlalchemy import Vector

    # Base filters
    base_filter = [Memory.user_id == user_id, Memory.status == "active"]
    if body.type:
        base_filter.append(Memory.type == body.type.value)
    if body.layer:
        base_filter.append(Memory.layer == body.layer.value)
    if body.tags:
        for tag in body.tags:
            base_filter.append(Memory.tags.contains([tag]))
    if body.project_id:
        base_filter.append(
            (Memory.scope_global.is_(True)) | (Memory.scope_projects.contains([body.project_id]))
        )

    # Try vector search first
    query_embedding = await get_embedding(body.query)
    vector_results: list[tuple[Memory, float]] = []

    if query_embedding is not None:
        # Vector similarity search using pgvector cosine distance
        vector_query = (
            select(
                Memory,
                Memory.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(*base_filter)
            .where(Memory.embedding.isnot(None))
            .order_by("distance")
            .limit(body.top_k * 2)  # Get more candidates for re-ranking
        )
        result = await session.execute(vector_query)
        for row in result:
            mem = row[0]
            distance = row[1]
            similarity = 1.0 - distance  # cosine_distance → similarity
            if similarity >= 0.3:  # Minimum threshold
                vector_results.append((mem, similarity))

    # Also do keyword search (fallback + complement)
    keyword_query = select(Memory).where(*base_filter)
    result = await session.execute(keyword_query)
    all_memories = result.scalars().all()

    keyword_results: list[tuple[Memory, float]] = []
    query_lower = body.query.lower()
    query_words = query_lower.split()

    for mem in all_memories:
        searchable = f"{mem.title} {mem.content} {' '.join(mem.tags)}".lower()
        matches = sum(1 for w in query_words if w in searchable)
        score = matches / len(query_words) if query_words else 0.0
        if score >= 0.3:
            keyword_results.append((mem, score))

    # Merge: vector (weight 0.7) + keyword (weight 0.3)
    scored_map: dict[uuid.UUID, tuple[Memory, float]] = {}

    for mem, sim in vector_results:
        scored_map[mem.id] = (mem, sim * 0.7)

    for mem, kw_score in keyword_results:
        if mem.id in scored_map:
            existing_mem, existing_score = scored_map[mem.id]
            scored_map[mem.id] = (existing_mem, existing_score + kw_score * 0.3)
        else:
            scored_map[mem.id] = (mem, kw_score * 0.3)

    # Sort by combined score
    final_results = sorted(scored_map.values(), key=lambda x: x[1], reverse=True)
    top_results = final_results[: body.top_k]

    return SearchResponse(
        results=[
            SearchResultItem(
                id=mem.id,
                title=mem.title,
                content=mem.content,
                type=mem.type,  # type: ignore[arg-type]
                layer=mem.layer,  # type: ignore[arg-type]
                score=round(score, 3),
                tags=mem.tags,
            )
            for mem, score in top_results
        ],
        total_searched=len(all_memories),
    )
