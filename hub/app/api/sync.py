"""Sync and render API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.config import settings
from app.core.database import get_session
from app.models.memory import Memory, SyncLog
from app.schemas.memory import (
    MemoryResponse,
    RenderRequest,
    RenderResponse,
    SyncPullRequest,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
)
from app.services.renderer import render_memories
from app.services.token_counter import count_tokens

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/push", response_model=SyncPushResponse)
async def push_sync(
    body: SyncPushRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> SyncPushResponse:
    """Push local memories to Hub."""
    created = 0
    updated = 0
    unchanged = 0
    affected_ids: list[str] = []

    for item in body.memories:
        if item.id:
            # Try to find existing
            result = await session.execute(
                select(Memory).where(Memory.id == item.id, Memory.user_id == user_id)
            )
            existing = result.scalar_one_or_none()
        else:
            existing = None

        if existing:
            # Check if content changed
            if existing.content == item.content and existing.title == item.title:
                unchanged += 1
                continue

            existing.title = item.title
            existing.content = item.content
            existing.type = item.type.value
            existing.layer = item.layer.value
            existing.priority = item.priority
            existing.tags = item.tags
            existing.status = item.status.value
            existing.scope_global = item.scope.global_
            existing.scope_projects = item.scope.projects
            existing.scope_exclude = item.scope.exclude_projects
            existing.source = item.source.value
            existing.token_count = count_tokens(item.content)
            updated += 1
            affected_ids.append(str(existing.id))
        else:
            # Create new
            memory = Memory(
                id=item.id or None,
                user_id=user_id,
                title=item.title,
                content=item.content,
                type=item.type.value,
                layer=item.layer.value,
                priority=item.priority,
                tags=item.tags,
                status=item.status.value,
                scope_global=item.scope.global_,
                scope_projects=item.scope.projects,
                scope_exclude=item.scope.exclude_projects,
                source=item.source.value,
                token_count=count_tokens(item.content),
            )
            session.add(memory)
            await session.flush()
            created += 1
            affected_ids.append(str(memory.id))

    # Log sync
    log = SyncLog(
        user_id=user_id,
        action="push",
        memories_affected=affected_ids,
        client_info=body.client_info,
    )
    session.add(log)

    return SyncPushResponse(created=created, updated=updated, unchanged=unchanged, conflicts=[])


@router.post("/pull", response_model=SyncPullResponse)
async def pull_sync(
    body: SyncPullRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> SyncPullResponse:
    """Pull memories from Hub since a given timestamp."""
    query = select(Memory).where(Memory.user_id == user_id)

    if not body.include_pending:
        query = query.where(Memory.status != "pending")

    if body.since:
        query = query.where(Memory.updated_at >= body.since)

    query = query.order_by(Memory.updated_at.desc())
    result = await session.execute(query)
    memories = result.scalars().all()

    # Log sync
    log = SyncLog(
        user_id=user_id,
        action="pull",
        memories_affected=[str(m.id) for m in memories],
    )
    session.add(log)

    return SyncPullResponse(
        memories=memories,  # type: ignore[arg-type]
        total=len(memories),
        server_time=datetime.now(timezone.utc),
    )


@router.post("/render", response_model=RenderResponse)
async def render(
    body: RenderRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> RenderResponse:
    """Render memories into target CLI format."""
    # Fetch relevant memories
    query = select(Memory).where(Memory.user_id == user_id, Memory.status == "active")

    if body.layer:
        query = query.where(Memory.layer == body.layer.value)
    else:
        # Default: L0 global + L1 for project
        query = query.where(Memory.layer.in_(["L0", "L1"]))

    if body.project_id:
        query = query.where(
            (Memory.scope_global.is_(True)) | (Memory.scope_projects.contains([body.project_id]))
        )
    else:
        query = query.where(Memory.scope_global.is_(True))

    query = query.order_by(Memory.priority.desc())
    result = await session.execute(query)
    memories = list(result.scalars().all())

    # Render with token limit
    max_tokens = settings.l0_max_tokens if body.layer and body.layer.value == "L0" else (
        settings.l0_max_tokens + settings.l1_max_tokens
    )

    content, included, truncated = render_memories(memories, body.target, max_tokens)
    token_count = count_tokens(content)

    return RenderResponse(
        content=content,
        token_count=token_count,
        memories_included=included,
        memories_truncated=truncated,
    )
