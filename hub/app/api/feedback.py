"""Memory feedback API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Memory, MemoryFeedback
from app.schemas.feedback import (
    CARD_REVIEW_CONTEXT,
    MemoryCardReviewCreate,
    MemoryCardReviewResponse,
    MemoryFeedbackBatchCreate,
    MemoryFeedbackBatchResponse,
    MemoryFeedbackCreate,
    MemoryFeedbackCreateResponse,
    MemoryFeedbackSummary,
)
from app.services.content_safety import require_safe_content

router = APIRouter(prefix="/memory-feedback", tags=["memory-feedback"])


async def _ensure_memory(
    session: AsyncSession,
    memory_id: uuid.UUID,
    user_id: str,
) -> Memory:
    result = await session.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return memory


async def _feedback_summary(
    session: AsyncSession,
    memory_id: uuid.UUID,
    user_id: str,
) -> MemoryFeedbackSummary:
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
    return MemoryFeedbackSummary(
        memory_id=memory_id,
        total=sum(ratings.values()),
        ratings=ratings,
        last_feedback_at=last_feedback_at,
    )


async def _create_feedback(
    session: AsyncSession,
    body: MemoryFeedbackCreate,
    user_id: str,
) -> MemoryFeedbackCreateResponse:
    require_safe_content(body.note, body.task_context)
    await _ensure_memory(session, body.memory_id, user_id)
    feedback = MemoryFeedback(
        user_id=user_id,
        memory_id=body.memory_id,
        rating=body.rating.value,
        note=body.note,
        task_context=body.task_context,
        used_by=body.used_by.value,
        confidence=body.confidence.value,
        source=body.source.value,
    )
    session.add(feedback)
    await session.flush()
    return MemoryFeedbackCreateResponse(
        feedback=feedback,  # type: ignore[arg-type]
        summary=await _feedback_summary(session, body.memory_id, user_id),
    )


@router.post("", response_model=MemoryFeedbackCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_memory_feedback(
    body: MemoryFeedbackCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> MemoryFeedbackCreateResponse:
    """Record one memory usefulness feedback signal without mutating memory status."""
    return await _create_feedback(session, body, user_id)


@router.post(
    "/batch", response_model=MemoryFeedbackBatchResponse, status_code=status.HTTP_201_CREATED
)
async def create_memory_feedback_batch(
    body: MemoryFeedbackBatchCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> MemoryFeedbackBatchResponse:
    """Record several memory feedback signals in one request."""
    items = []
    for item in body.items:
        items.append(await _create_feedback(session, item, user_id))
    return MemoryFeedbackBatchResponse(items=items)


@router.post(
    "/card-review",
    response_model=MemoryCardReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_memory_card_review(
    body: MemoryCardReviewCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> MemoryCardReviewResponse:
    """Record one human card judgment; quarantine an incorrect memory atomically."""
    require_safe_content(body.note)
    memory = await session.scalar(
        select(Memory)
        .where(Memory.id == body.memory_id, Memory.user_id == user_id)
        .with_for_update()
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    if memory.status not in {"active", "ai_review"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Memory is no longer in the card review queue",
        )
    already_reviewed = await session.scalar(
        select(MemoryFeedback.id)
        .where(
            MemoryFeedback.user_id == user_id,
            MemoryFeedback.memory_id == body.memory_id,
            MemoryFeedback.task_context == CARD_REVIEW_CONTEXT,
            MemoryFeedback.used_by == "user",
            MemoryFeedback.source == "web",
        )
        .limit(1)
    )
    if already_reviewed is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Memory card was already reviewed",
        )

    feedback = MemoryFeedback(
        user_id=user_id,
        memory_id=body.memory_id,
        rating=body.rating,
        note=body.note,
        task_context=CARD_REVIEW_CONTEXT,
        used_by="user",
        confidence="high",
        source="web",
    )
    session.add(feedback)
    if body.rating == "wrong":
        memory.status = "pending"
    await session.flush()
    return MemoryCardReviewResponse(
        feedback=feedback,  # type: ignore[arg-type]
        memory_status=memory.status,
    )


@router.get("/{memory_id}/summary", response_model=MemoryFeedbackSummary)
async def get_memory_feedback_summary(
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> MemoryFeedbackSummary:
    """Return aggregated feedback for one memory."""
    await _ensure_memory(session, memory_id, user_id)
    return await _feedback_summary(session, memory_id, user_id)
