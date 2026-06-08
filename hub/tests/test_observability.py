"""Unit tests for observability API endpoints."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.memory import Memory, SleepSession


def _make_sleep_session(user_id: str) -> MagicMock:
    sleep_session = MagicMock(spec=SleepSession)
    sleep_session.id = uuid.uuid4()
    sleep_session.user_id = user_id
    sleep_session.project_id = "qzhqzh/EchoMe"
    sleep_session.status = "draft"
    sleep_session.mode = "client_generated"
    sleep_session.candidate_memory_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    sleep_session.text_proposal = None
    sleep_session.json_proposal = None
    sleep_session.created_at = datetime.now(timezone.utc)
    sleep_session.updated_at = datetime.now(timezone.utc)
    sleep_session.applied_at = None
    return sleep_session


def _make_memory(user_id: str, status: str = "active") -> MagicMock:
    memory = MagicMock(spec=Memory)
    memory.id = uuid.uuid4()
    memory.user_id = user_id
    memory.title = "Observed memory"
    memory.type = "context"
    memory.layer = "L2"
    memory.status = status
    memory.tags = ["observability"]
    memory.is_core = False
    memory.sleep_state = "fresh"
    memory.superseded_by = None
    memory.derived_from = []
    memory.updated_at = datetime.now(timezone.utc)
    return memory


class TestObservability:
    """Tests for read-only observability endpoints."""

    @pytest.mark.asyncio
    async def test_list_sleep_sessions(self, test_user_id: str):
        from app.api.observability import list_sleep_sessions

        sleep_session = _make_sleep_session(test_user_id)
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        sessions_result = MagicMock()
        sessions_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[sleep_session]))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[count_result, sessions_result])

        result = await list_sleep_sessions(
            project_id=None,
            status_filter=None,
            offset=0,
            limit=50,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result["total"] == 1
        assert result["items"][0]["candidate_count"] == 2

    @pytest.mark.asyncio
    async def test_memory_graph_returns_nodes_and_edges(self, test_user_id: str):
        from app.api.observability import get_memory_graph

        memory = _make_memory(test_user_id)
        memories_result = MagicMock()
        memories_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[memory]))
        edges_result = MagicMock()
        edges_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[memories_result, edges_result])

        result = await get_memory_graph(
            project_id=None,
            include_inactive=False,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result["nodes"][0]["status"] == "active"
        assert result["edges"] == []
