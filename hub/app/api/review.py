"""Review API routes for AI-suggested memories."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory
from app.schemas.memory import MemoryListResponse

router = APIRouter(prefix="/review", tags=["review"])


class ApproveRequest(BaseModel):
    """Optional overrides when approving."""

    layer: str | None = None
    priority: int | None = Field(None, ge=1, le=10)


@router.get("/pending", response_model=MemoryListResponse)
async def list_pending(
    review_status: str = Query("ai_review", alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> MemoryListResponse:
    """List AI-written memories for review. Defaults to ai_review."""
    if review_status not in {"ai_review", "pending"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Review status must be ai_review or pending",
        )

    query = select(Memory).where(
        Memory.user_id == user_id,
        Memory.status == review_status,
    )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    query = query.order_by(Memory.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    memories = result.scalars().all()

    return MemoryListResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=memories,  # type: ignore[arg-type]
    )


@router.post("/{memory_id}/approve", status_code=status.HTTP_200_OK)
async def approve_memory(
    memory_id: uuid.UUID,
    body: ApproveRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, str]:
    """Approve an AI-written memory - sets status to active."""
    result = await session.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.status.in_(["ai_review", "pending"]),
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review memory not found",
        )

    memory.status = "active"
    if body:
        if body.layer:
            memory.layer = body.layer
        if body.priority is not None:
            memory.priority = body.priority

    return {"status": "approved", "id": str(memory.id)}


@router.post("/{memory_id}/reject", status_code=status.HTTP_200_OK)
async def reject_memory(
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, str]:
    """Reject an AI-written memory - sets status to archived."""
    result = await session.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.status.in_(["ai_review", "pending"]),
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review memory not found",
        )

    memory.status = "archived"
    return {"status": "rejected", "id": str(memory.id)}
