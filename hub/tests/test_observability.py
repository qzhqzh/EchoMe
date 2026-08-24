"""Unit tests for observability API endpoints."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.memory import Memory, MemoryEdge, SleepSession
from app.models.project_knowledge import ReliabilityAssessment


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
    memory.content = "Observed memory content"
    memory.type = "context"
    memory.layer = "L2"
    memory.priority = 5
    memory.status = status
    memory.source = "manual"
    memory.token_count = 10
    memory.scope_global = False
    memory.scope_projects = ["qzhqzh/EchoMe"]
    memory.scope_exclude = []
    memory.tags = ["observability"]
    memory.is_core = False
    memory.sleep_state = "fresh"
    memory.last_accessed_at = None
    memory.access_count = 0
    memory.superseded_by = None
    memory.derived_from = []
    memory.created_at = datetime.now(timezone.utc)
    memory.updated_at = datetime.now(timezone.utc)
    return memory


def _make_edge(source_id: uuid.UUID, target_id: uuid.UUID) -> MagicMock:
    edge = MagicMock(spec=MemoryEdge)
    edge.id = uuid.uuid4()
    edge.source_memory_id = source_id
    edge.target_memory_id = target_id
    edge.relation = "derived_from"
    edge.reason = "test relation"
    edge.sleep_session_id = uuid.uuid4()
    edge.created_by = "sleep"
    edge.created_at = datetime.now(timezone.utc)
    return edge


class TestObservability:
    """Tests for read-only observability endpoints."""

    @pytest.mark.asyncio
    async def test_list_sleep_sessions(self, test_user_id: str):
        from app.api.observability import list_sleep_sessions

        sleep_session = _make_sleep_session(test_user_id)
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        sessions_result = MagicMock()
        sessions_result.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[sleep_session])
        )

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

    @pytest.mark.asyncio
    async def test_reliability_history_is_metadata_only(self, test_user_id: str):
        from app.api.observability import list_reliability_assessments

        assessment = ReliabilityAssessment(
            id=uuid.uuid4(),
            user_id=test_user_id,
            project_id="qzhqzh/EchoMe",
            subject_type="memory",
            subject_id=uuid.uuid4(),
            assessment_class="environment_bound",
            support_state="needs_verification",
            confidence=0.78,
            reason_codes=["volatile_requires_verification"],
            evidence_refs=[],
            source_watermark={"status": "active"},
            source_fingerprint="a" * 64,
            producer="echome.rules.v1",
            schema_version=1,
            assessed_at=datetime.now(timezone.utc),
        )
        result_set = MagicMock()
        result_set.scalars.return_value.all.return_value = [assessment]
        mock_session = AsyncMock()
        mock_session.execute.return_value = result_set

        result = await list_reliability_assessments(
            project_id=None,
            subject_type="memory",
            subject_id=None,
            support_state=None,
            limit=100,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result["items"][0]["support_state"] == "needs_verification"
        assert "content" not in result["items"][0]

    @pytest.mark.asyncio
    async def test_context_policy_readiness_is_read_only(self, test_user_id: str, monkeypatch):
        from app.api.observability import get_context_policy_readiness

        expected = {
            "schema_version": "echome.context-policy-readiness.v1",
            "status": "insufficient_data",
            "auto_enforce": False,
        }
        evaluate = AsyncMock(return_value=expected)
        monkeypatch.setattr(
            "app.api.observability.evaluate_context_policy_readiness",
            evaluate,
        )
        mock_session = AsyncMock()

        result = await get_context_policy_readiness(
            project_id="qzhqzh/EchoMe",
            window_days=45,
            max_runs=500,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result == expected
        evaluate.assert_awaited_once_with(
            mock_session,
            user_id=test_user_id,
            project_id="qzhqzh/EchoMe",
            window_days=45,
            max_runs=500,
        )

    @pytest.mark.asyncio
    async def test_memory_neighbors_returns_local_graph_and_assessment(self, test_user_id: str):
        from app.api.observability import get_memory_neighbors

        center = _make_memory(test_user_id)
        neighbor = _make_memory(test_user_id)
        edge = _make_edge(center.id, neighbor.id)

        center_result = MagicMock()
        center_result.scalar_one_or_none.return_value = center
        edge_result = MagicMock()
        edge_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[edge]))
        memories_result = MagicMock()
        memories_result.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[center, neighbor])
        )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[center_result, edge_result, memories_result])

        result = await get_memory_neighbors(
            memory_id=center.id,
            depth=1,
            include_inactive=False,
            limit=20,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result["center_memory_id"] == str(center.id)
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert str(center.id) in result["temporal_assessments"]

    def test_temporal_assessment_separates_dormant_project_from_stale(self, test_user_id: str):
        from datetime import timedelta

        from app.api.observability import _temporal_assessment

        memory = _make_memory(test_user_id)
        memory.updated_at = datetime.now(timezone.utc) - timedelta(days=400)
        project_activity_at = datetime.now(timezone.utc) - timedelta(days=220)

        assessment = _temporal_assessment(memory, project_activity_at)

        assert assessment["classification"] == "dormant_project"
        assert "project_dormant_not_stale" in assessment["signals"]

    def test_temporal_assessment_flags_time_sensitive_memory(self, test_user_id: str):
        from app.api.observability import _temporal_assessment

        memory = _make_memory(test_user_id)
        memory.title = "Temporary workaround for current routing"
        memory.content = "This is a temporary workaround."
        memory.layer = "L2"
        memory.tags = []

        assessment = _temporal_assessment(memory, memory.updated_at)

        assert assessment["classification"] == "needs_verification"
        assert any(signal.startswith("temporal_terms:") for signal in assessment["signals"])
