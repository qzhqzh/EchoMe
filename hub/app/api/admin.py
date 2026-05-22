"""Admin API: user management, system stats, memory moderation."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.memory import Memory, Project, SyncLog
from app.models.user import User
from app.schemas.user import UserInfo

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Admin Guard ---


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Ensure the current user is an admin."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# --- Schemas ---


class SystemStats(BaseModel):
    """System-wide statistics."""

    total_users: int
    total_memories: int
    total_projects: int
    total_syncs: int
    memories_active: int
    memories_pending: int
    memories_public: int
    memories_last_7d: int
    users_last_7d: int


class UserListItem(BaseModel):
    """User item for admin listing."""

    id: uuid.UUID
    github_id: int
    username: str
    email: str | None = None
    avatar_url: str | None = None
    role: str
    created_at: datetime
    last_login_at: datetime | None = None
    memory_count: int = 0

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Paginated user list."""

    total: int
    items: list[UserListItem]


class UpdateRoleRequest(BaseModel):
    """Request to change a user's role."""

    role: str  # "admin" or "user"


# --- Routes ---


@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> SystemStats:
    """Get system-wide statistics (admin only)."""
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    total_memories = (await session.execute(select(func.count()).select_from(Memory))).scalar_one()
    total_projects = (await session.execute(select(func.count()).select_from(Project))).scalar_one()
    total_syncs = (await session.execute(select(func.count()).select_from(SyncLog))).scalar_one()

    memories_active = (await session.execute(
        select(func.count()).select_from(
            select(Memory).where(Memory.status == "active").subquery()
        )
    )).scalar_one()

    memories_pending = (await session.execute(
        select(func.count()).select_from(
            select(Memory).where(Memory.status == "pending").subquery()
        )
    )).scalar_one()

    memories_public = (await session.execute(
        select(func.count()).select_from(
            select(Memory).where(Memory.visibility == "public").subquery()
        )
    )).scalar_one()

    memories_last_7d = (await session.execute(
        select(func.count()).select_from(
            select(Memory).where(Memory.created_at >= seven_days_ago).subquery()
        )
    )).scalar_one()

    users_last_7d = (await session.execute(
        select(func.count()).select_from(
            select(User).where(User.created_at >= seven_days_ago).subquery()
        )
    )).scalar_one()

    return SystemStats(
        total_users=total_users,
        total_memories=total_memories,
        total_projects=total_projects,
        total_syncs=total_syncs,
        memories_active=memories_active,
        memories_pending=memories_pending,
        memories_public=memories_public,
        memories_last_7d=memories_last_7d,
        users_last_7d=users_last_7d,
    )


@router.get("/users", response_model=UserListResponse)
async def list_users(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserListResponse:
    """List all users with memory counts (admin only)."""
    # Total count
    total = (await session.execute(select(func.count()).select_from(User))).scalar_one()

    # Fetch users
    result = await session.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
    )
    users = result.scalars().all()

    # Get memory counts per user
    items = []
    for u in users:
        mem_count = (await session.execute(
            select(func.count()).select_from(
                select(Memory).where(Memory.user_id == str(u.id)).subquery()
            )
        )).scalar_one()

        items.append(UserListItem(
            id=u.id,
            github_id=u.github_id,
            username=u.username,
            email=u.email,
            avatar_url=u.avatar_url,
            role=u.role,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            memory_count=mem_count,
        ))

    return UserListResponse(total=total, items=items)


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    body: UpdateRoleRequest,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    """Change a user's role (admin only)."""
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = body.role
    return {"status": "ok", "username": user.username, "role": user.role}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    """Delete a user and all their data (admin only)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete user's memories
    await session.execute(
        select(Memory).where(Memory.user_id == str(user_id))
    )
    from sqlalchemy import delete
    await session.execute(delete(Memory).where(Memory.user_id == str(user_id)))
    await session.execute(delete(Project).where(Project.user_id == str(user_id)))
    await session.execute(delete(SyncLog).where(SyncLog.user_id == str(user_id)))
    await session.delete(user)

    return {"status": "deleted", "username": user.username}


@router.delete("/memories/{memory_id}")
async def admin_delete_memory(
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """Delete any memory regardless of owner (admin only)."""
    result = await session.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    await session.delete(memory)
    return {"status": "deleted", "id": str(memory_id)}
