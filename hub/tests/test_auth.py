"""Unit tests for hub auth API endpoints."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.jwt import ALGORITHM, create_access_token, decode_access_token


class TestJWT:
    """Test JWT token creation and verification."""

    def test_create_access_token_returns_tuple(self):
        """create_access_token returns (token_str, expires_in_seconds)."""
        user_id = uuid.uuid4()
        token, expires_in = create_access_token(user_id, "testuser", "user")

        assert isinstance(token, str)
        assert len(token) > 0
        assert isinstance(expires_in, int)
        assert expires_in > 0

    def test_decode_valid_token(self):
        """A freshly created token should decode successfully."""
        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, "myuser", "admin")

        payload = decode_access_token(token)

        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["username"] == "myuser"
        assert payload["role"] == "admin"

    def test_decode_invalid_token_returns_none(self):
        """An invalid token should return None."""
        result = decode_access_token("invalid.token.string")
        assert result is None

    def test_decode_empty_token_returns_none(self):
        """An empty string should return None."""
        result = decode_access_token("")
        assert result is None

    def test_token_contains_expected_claims(self):
        """Token payload should have sub, username, role, exp claims."""
        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, "user1", "user")

        payload = decode_access_token(token)
        assert "sub" in payload
        assert "username" in payload
        assert "role" in payload
        assert "exp" in payload

    def test_different_users_get_different_tokens(self):
        """Two different users should produce different tokens."""
        token1, _ = create_access_token(uuid.uuid4(), "user1", "user")
        token2, _ = create_access_token(uuid.uuid4(), "user2", "user")

        assert token1 != token2


class TestAuthDependency:
    """Test the auth dependency (get_current_user / verify_token)."""

    @pytest.mark.asyncio
    async def test_valid_jwt_resolves_user(self):
        """A valid JWT should resolve to the correct user."""
        from unittest.mock import patch

        from fastapi.security import HTTPAuthorizationCredentials

        from app.core.auth import get_current_user
        from app.models.user import User

        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, "testuser", "user")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.username = "testuser"
        mock_user.role = "user"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute = AsyncMock(return_value=mock_result)

        user = await get_current_user(credentials=credentials, session=mock_session)
        assert user.id == user_id
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_invalid_jwt_raises_401(self):
        """An invalid JWT should raise HTTPException with 401."""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.core.auth import get_current_user

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="bad.token.here"
        )
        mock_session = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, session=mock_session)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_emergency_token_resolves_admin(self):
        """Emergency auth token should map to first admin user."""
        from fastapi.security import HTTPAuthorizationCredentials

        from app.core.auth import get_current_user
        from app.models.user import User

        mock_admin = MagicMock(spec=User)
        mock_admin.id = uuid.uuid4()
        mock_admin.username = "admin"
        mock_admin.role = "admin"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_admin
        mock_session.execute = AsyncMock(return_value=mock_result)

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-emergency-token"
        )

        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.auth_token = "test-emergency-token"
            user = await get_current_user(credentials=credentials, session=mock_session)

        assert user.username == "admin"
        assert user.role == "admin"

    @pytest.mark.asyncio
    async def test_valid_jwt_user_not_found_raises_401(self):
        """If JWT is valid but user doesn't exist in DB, should raise 401."""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.core.auth import get_current_user

        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, "ghost", "user")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # User not found
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, session=mock_session)

        assert exc_info.value.status_code == 401


class TestAuthEndpoints:
    """Test auth API endpoint logic."""

    @pytest.mark.asyncio
    async def test_github_login_returns_url(self):
        """GET /auth/github should return a GitHub OAuth URL."""
        from app.api.auth import github_login

        with patch("app.api.auth.settings") as mock_settings:
            mock_settings.github_client_id = "test_client_id"

            result = await github_login()

        assert "github.com/login/oauth/authorize" in result.url
        assert "test_client_id" in result.url

    @pytest.mark.asyncio
    async def test_github_login_no_config_raises_503(self):
        """GET /auth/github should raise 503 if OAuth not configured."""
        from fastapi import HTTPException

        from app.api.auth import github_login

        with patch("app.api.auth.settings") as mock_settings:
            mock_settings.github_client_id = ""

            with pytest.raises(HTTPException) as exc_info:
                await github_login()

            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_me_returns_user_info(self):
        """GET /auth/me should return UserInfo for authenticated user."""
        from app.api.auth import get_me
        from app.models.user import User

        mock_user = MagicMock(spec=User)
        mock_user.id = uuid.uuid4()
        mock_user.github_id = 12345
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.avatar_url = "https://github.com/avatar.png"
        mock_user.role = "user"
        mock_user.created_at = datetime.now(timezone.utc)
        mock_user.last_login_at = datetime.now(timezone.utc)

        result = await get_me(user=mock_user)

        assert result.username == "testuser"
        assert result.role == "user"
        assert result.github_id == 12345

    @pytest.mark.asyncio
    async def test_refresh_token_returns_new_token(self):
        """POST /auth/refresh should return a new valid token."""
        from app.api.auth import refresh_token
        from app.models.user import User

        mock_user = MagicMock(spec=User)
        mock_user.id = uuid.uuid4()
        mock_user.username = "refreshuser"
        mock_user.role = "user"
        mock_user.github_id = 99999
        mock_user.email = None
        mock_user.avatar_url = None
        mock_user.created_at = datetime.now(timezone.utc)
        mock_user.last_login_at = datetime.now(timezone.utc)

        result = await refresh_token(user=mock_user)

        assert result.access_token
        assert result.expires_in > 0
        assert result.user.username == "refreshuser"

        # Verify the new token is valid
        payload = decode_access_token(result.access_token)
        assert payload is not None
        assert payload["username"] == "refreshuser"
