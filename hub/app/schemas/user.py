"""Pydantic schemas for user-related requests/responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class UserInfo(BaseModel):
    """Public user information returned by /auth/me."""

    id: uuid.UUID
    github_id: int
    username: str
    email: str | None = None
    avatar_url: str | None = None
    role: str
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """JWT token response after successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserInfo


class GitHubLoginURL(BaseModel):
    """Response containing the GitHub OAuth authorization URL."""

    url: str
