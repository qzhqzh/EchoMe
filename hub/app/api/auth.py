"""Auth API: GitHub OAuth login, callback, me, refresh."""

from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.core.jwt import create_access_token, decode_access_token
from app.models.user import User
from app.schemas.user import GitHubLoginURL, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


@router.get("/github", response_model=GitHubLoginURL)
async def github_login() -> GitHubLoginURL:
    """Return the GitHub OAuth authorization URL for the frontend to redirect to."""
    if not settings.github_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured (missing ECHOME_GITHUB_CLIENT_ID)",
        )

    params = {
        "client_id": settings.github_client_id,
        "scope": "read:user user:email",
    }
    url = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
    return GitHubLoginURL(url=url)


@router.get("/github/callback", response_model=TokenResponse)
async def github_callback(
    code: str,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Handle GitHub OAuth callback: exchange code for token, create/update user, return JWT."""
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured",
        )

    # Step 1: Exchange code for GitHub access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )

    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to exchange code with GitHub",
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        error_desc = token_data.get("error_description", "Unknown error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {error_desc}",
        )

    # Step 2: Fetch GitHub user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    if user_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch user info from GitHub",
        )

    gh_user = user_resp.json()
    github_id: int = gh_user["id"]
    username: str = gh_user["login"]
    email: str | None = gh_user.get("email")
    avatar_url: str | None = gh_user.get("avatar_url")

    # Step 3: Create or update user in DB
    result = await session.execute(
        select(User).where(User.github_id == github_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        # Determine role: first user becomes admin
        count_result = await session.execute(select(func.count()).select_from(User))
        user_count = count_result.scalar() or 0
        role = "admin" if user_count == 0 else "user"

        user = User(
            github_id=github_id,
            username=username,
            email=email,
            avatar_url=avatar_url,
            role=role,
            last_login_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.flush()  # Populate user.id
    else:
        # Update existing user info
        user.username = username
        user.email = email
        user.avatar_url = avatar_url
        user.last_login_at = datetime.now(timezone.utc)

    # Step 4: Issue JWT
    token, expires_in = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserInfo.model_validate(user),
    )


@router.get("/me", response_model=UserInfo)
async def get_me(
    user: User = Depends(get_current_user),
) -> UserInfo:
    """Return the current authenticated user's information."""
    return UserInfo.model_validate(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    user: User = Depends(get_current_user),
) -> TokenResponse:
    """Refresh the JWT token for the current user."""
    token, expires_in = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserInfo.model_validate(user),
    )
