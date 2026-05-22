"""Market API: browse, search, fork public memories."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_id
from app.core.database import get_session
from app.models.memory import Memory
from app.schemas.memory import MemoryResponse, MemoryType, Visibility
from app.services.embedding import get_embedding

router = APIRouter(prefix="/market", tags=["market"])


# --- Schemas ---


class MarketListItem(BaseModel):
    """Public memory item for market listing."""

    id: uuid.UUID
    title: str
    content: str
    type: str
    layer: str
    priority: int
    tags: list[str]
    source: str
    token_count: int
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MarketListResponse(BaseModel):
    """Paginated list of public memories."""

    total: int
    offset: int
    limit: int
    items: list[MarketListItem]


class MarketStatsResponse(BaseModel):
    """Market statistics."""

    total_public: int
    by_type: dict[str, int]
    recent_count_7d: int


class ForkResponse(BaseModel):
    """Response after forking a memory."""

    id: uuid.UUID
    title: str
    forked_from: uuid.UUID
    message: str = "Memory forked successfully"


# --- Routes ---


@router.get("/memories", response_model=MarketListResponse)
async def list_public_memories(
    type: str | None = None,
    layer: str | None = None,
    tags: str | None = None,
    q: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> MarketListResponse:
    """Browse public memories (no auth required)."""
    query = select(Memory).where(
        Memory.visibility == "public",
        Memory.status == "active",
    )

    if type:
        query = query.where(Memory.type == type)
    if layer:
        query = query.where(Memory.layer == layer)
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        for tag in tag_list:
            query = query.where(Memory.tags.contains([tag]))
    if q:
        # Simple keyword search in title and content
        search_term = f"%{q}%"
        query = query.where(
            (Memory.title.ilike(search_term)) | (Memory.content.ilike(search_term))
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # Fetch page
    query = query.order_by(Memory.priority.desc(), Memory.updated_at.desc())
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    memories = result.scalars().all()

    return MarketListResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=[MarketListItem.model_validate(m) for m in memories],
    )


@router.get("/memories/{memory_id}", response_model=MarketListItem)
async def get_public_memory(
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> MarketListItem:
    """Get a single public memory by ID (no auth required)."""
    result = await session.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.visibility == "public",
            Memory.status == "active",
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public memory not found",
        )
    return MarketListItem.model_validate(memory)


@router.post("/memories/{memory_id}/fork", response_model=ForkResponse)
async def fork_memory(
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> ForkResponse:
    """Fork a public memory into the current user's library."""
    # Find the source memory
    result = await session.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.visibility == "public",
            Memory.status == "active",
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public memory not found",
        )

    # Don't allow forking own memories
    if source.user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot fork your own memory",
        )

    # Create a copy for the current user
    forked = Memory(
        user_id=user_id,
        title=source.title,
        content=source.content,
        type=source.type,
        layer=source.layer,
        priority=source.priority,
        tags=source.tags,
        status="active",
        scope_global=source.scope_global,
        scope_projects=[],  # Reset project scope for the new user
        scope_exclude=[],
        source="imported",
        visibility="private",  # Forked copies are private by default
        forked_from=source.id,
        token_count=source.token_count,
    )
    session.add(forked)
    await session.flush()

    return ForkResponse(
        id=forked.id,
        title=forked.title,
        forked_from=source.id,
    )


@router.get("/stats", response_model=MarketStatsResponse)
async def market_stats(
    session: AsyncSession = Depends(get_session),
) -> MarketStatsResponse:
    """Get market statistics (no auth required)."""
    # Total public memories
    total_result = await session.execute(
        select(func.count()).select_from(
            select(Memory)
            .where(Memory.visibility == "public", Memory.status == "active")
            .subquery()
        )
    )
    total_public = total_result.scalar_one()

    # Count by type
    type_result = await session.execute(
        select(Memory.type, func.count())
        .where(Memory.visibility == "public", Memory.status == "active")
        .group_by(Memory.type)
    )
    by_type = {row[0]: row[1] for row in type_result}

    # Recent 7 days
    from datetime import timedelta

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_result = await session.execute(
        select(func.count()).select_from(
            select(Memory)
            .where(
                Memory.visibility == "public",
                Memory.status == "active",
                Memory.created_at >= seven_days_ago,
            )
            .subquery()
        )
    )
    recent_count = recent_result.scalar_one()

    return MarketStatsResponse(
        total_public=total_public,
        by_type=by_type,
        recent_count_7d=recent_count,
    )
