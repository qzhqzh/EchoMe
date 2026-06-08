"""Unit tests for memory sleep API helpers and candidate pagination."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.memory import Memory


def _make_memory(
    title: str,
    project_id: str = "qzhqzh/EchoMe",
    is_core: bool = False,
    sleep_state: str = "fresh",
    status: str = "active",
) -> MagicMock:
    memory = MagicMock(spec=Memory)
    memory.id = uuid.uuid4()
    memory.title = title
    memory.content = f"{title} content"
    memory.type = "context"
    memory.layer = "L2"
    memory.priority = 5
    memory.tags = ["sleep"]
    memory.status = status
    memory.source = "manual"
    memory.scope_global = False
    memory.scope_projects = [project_id]
    memory.scope_exclude = []
    memory.is_core = is_core
    memory.sleep_state = sleep_state
    memory.access_count = 0
    memory.last_accessed_at = None
    memory.superseded_by = None
    memory.derived_from = []
    memory.created_at = datetime.now(timezone.utc)
    memory.updated_at = datetime.now(timezone.utc)
    return memory


class TestSleepCandidates:
    """Tests for sleep candidate pagination and protection."""

    @pytest.mark.asyncio
    async def test_candidates_page_is_not_plain_top_k(self, test_user_id: str):
        from app.api.memory_sleep import get_sleep_candidates
        from app.schemas.sleep import SleepCandidatesRequest

        memories = [
            _make_memory("Memory 1"),
            _make_memory("Memory 2", is_core=True),
            _make_memory("Memory 3", status="ai_review"),
            _make_memory("Memory 4", sleep_state="reviewed"),
            _make_memory("Memory 5"),
        ]
        memory_result = MagicMock()
        memory_result.scalars.return_value = MagicMock(all=MagicMock(return_value=memories))
        edge_result = MagicMock()
        edge_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[memory_result, edge_result])
        def add_with_id(obj):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=add_with_id)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        body = SleepCandidatesRequest(
            project_id="qzhqzh/EchoMe",
            page_size=2,
            include_protected=True,
        )

        result = await get_sleep_candidates(body=body, session=mock_session, user_id=test_user_id)

        assert len(result.candidates) == 2
        assert "ai_review" in {m.status.value for m in result.candidates}
        assert result.has_more is True
        assert result.next_cursor == 2
        assert {m.protection_reason for m in result.protected_memories} == {
            "core",
            "already_organized",
        }


class TestSleepPlanValidation:
    """Tests for JSON plan validation."""

    def test_default_candidate_statuses_exclude_deprecated_and_archived(self):
        from app.schemas.sleep import SleepCandidatesRequest

        body = SleepCandidatesRequest(project_id="qzhqzh/EchoMe")

        assert {s.value for s in body.status} == {"active", "ai_review", "pending"}

    def test_plan_input_ids_must_be_candidate_subset(self):
        from app.api.memory_sleep import _validate_plan_header

        sleep_session = MagicMock()
        sleep_session.id = uuid.uuid4()
        sleep_session.candidate_memory_ids = [str(uuid.uuid4())]

        plan = {
            "schema_version": "memory_sleep_plan.v1",
            "session_id": str(sleep_session.id),
            "input_memory_ids": [str(uuid.uuid4())],
            "actions": [],
        }

        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_header(plan, sleep_session)

        assert exc_info.value.status_code == 400
        assert "subset" in exc_info.value.detail
