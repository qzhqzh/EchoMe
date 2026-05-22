"""Shared test fixtures for hub API tests."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.jwt import create_access_token
from app.main import app


@pytest.fixture
def test_user_id() -> str:
    """A fixed user UUID for tests."""
    return str(uuid.UUID("12345678-1234-1234-1234-123456789abc"))


@pytest.fixture
def test_user_id_uuid(test_user_id: str) -> uuid.UUID:
    """The test user UUID object."""
    return uuid.UUID(test_user_id)


@pytest.fixture
def auth_token(test_user_id_uuid: uuid.UUID) -> str:
    """A valid JWT token for the test user."""
    token, _ = create_access_token(
        user_id=test_user_id_uuid,
        username="testuser",
        role="user",
    )
    return token


@pytest.fixture
def admin_token(test_user_id_uuid: uuid.UUID) -> str:
    """A valid JWT token for an admin user."""
    admin_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    token, _ = create_access_token(
        user_id=admin_id,
        username="admin",
        role="admin",
    )
    return token


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    """Authorization headers with valid JWT."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def mock_session():
    """A mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def sample_memory_data() -> dict:
    """Valid memory creation payload."""
    return {
        "title": "Test Memory",
        "content": "This is a test memory for unit testing.",
        "type": "context",
        "layer": "L2",
        "priority": 5,
        "tags": ["test", "unit"],
        "status": "active",
        "scope": {
            "global": True,
            "projects": [],
            "exclude_projects": [],
        },
        "source": "manual",
        "visibility": "private",
    }


@pytest.fixture
def sample_memory_update_data() -> dict:
    """Valid memory full update payload."""
    return {
        "title": "Updated Memory",
        "content": "This memory has been updated.",
        "type": "method",
        "layer": "L1",
        "priority": 8,
        "tags": ["updated"],
        "status": "active",
        "scope": {
            "global": False,
            "projects": ["test/project"],
            "exclude_projects": [],
        },
        "source": "manual",
        "visibility": "private",
    }
