"""Authentication dependencies - JWT + legacy bearer token support."""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.jwt import decode_access_token
from app.models.user import User

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Verify token and return the current User object.

    Supports two modes:
    1. JWT token (multi-user) - decoded to get user_id
    2. Legacy bearer token (ECHOME_AUTH_TOKEN) - mapped to first admin user
    """
    token = credentials.credentials

    # Check legacy token first (backward compatibility)
    if token == settings.auth_token:
        # Map to first admin user
        result = await session.execute(
            select(User).where(User.role == "admin").order_by(User.created_at).limit(1)
        )
        admin_user = result.scalar_one_or_none()
        if admin_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No admin user found. Please login via GitHub OAuth first.",
            )
        return admin_user

    # Try JWT
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await session.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_current_user_id(
    user: User = Depends(get_current_user),
) -> str:
    """Return user_id as string - drop-in replacement for old verify_token."""
    return str(user.id)


# Backward-compatible alias so existing routes don't need changes
verify_token = get_current_user_id
