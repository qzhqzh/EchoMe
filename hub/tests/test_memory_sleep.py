"""Unit tests for memory sleep API helpers and candidate pagination."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.memory import Memory, SleepSession


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
    memory.token_count = 200
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


def _v2_plan(sleep_session: SleepSession, memories: list[MagicMock]) -> dict:
    input_ids = [str(memory.id) for memory in memories]
    return {
        "schema_version": "memory_sleep_plan.v2",
        "session_id": str(sleep_session.id),
        "input_memory_ids": input_ids,
        "preconditions": [
            {
                "memory_id": str(memory.id),
                "status": memory.status,
                "sleep_state": memory.sleep_state,
                "updated_at": memory.updated_at.isoformat(),
            }
            for memory in memories
        ],
        "actions": [
            {
                "op": "create_memory",
                "client_ref": "summary",
                "derived_from": input_ids,
                "memory": {
                    "title": "Git workflow summary",
                    "content": "Use pull requests for Git workflow changes.",
                    "type": "project",
                    "layer": "L1",
                    "priority": 8,
                    "tags": ["git", "workflow"],
                    "status": "active",
                    "scope": {
                        "global": False,
                        "projects": ["qzhqzh/EchoMe"],
                        "exclude_projects": [],
                    },
                },
            },
            *[
                {
                    "op": "update_memory_status",
                    "memory_id": str(memory.id),
                    "from_status": memory.status,
                    "to_status": "archived",
                    "superseded_by_ref": "summary",
                }
                for memory in memories
            ],
        ],
        "replay_cases": [
            {
                "case_id": "git-workflow",
                "query": "Git workflow pull request",
                "expected_memory_ids": [input_ids[0]],
                "top_k": 5,
            }
        ],
    }


class TestSleepCandidates:
    """Tests for sleep candidate pagination and protection."""

    @pytest.mark.asyncio
    async def test_candidates_page_is_not_plain_top_k(self, test_user_id: str, monkeypatch):
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

        monkeypatch.setattr(
            "app.api.memory_sleep.canonicalize_project_scopes",
            AsyncMock(return_value=["qzhqzh/EchoMe"]),
        )
        monkeypatch.setattr(
            "app.api.memory_sleep.project_scope_ids",
            AsyncMock(return_value=["EchoMe", "qzhqzh/EchoMe"]),
        )

        body = SleepCandidatesRequest(
            project_id="EchoMe",
            page_size=2,
            include_protected=True,
        )

        result = await get_sleep_candidates(body=body, session=mock_session, user_id=test_user_id)

        assert len(result.candidates) == 2
        assert result.project_id == "qzhqzh/EchoMe"
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

        assert set(body.status) == {"active", "ai_review", "pending"}
        assert body.plan_schema_version == "memory_sleep_plan.v1"
        legacy_body = SleepCandidatesRequest(
            project_id="qzhqzh/EchoMe",
            status=["deprecated", "archived"],
        )
        assert set(legacy_body.status) == {"deprecated", "archived"}

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

    def test_v1_actions_cannot_reference_memories_outside_the_session(self):
        from app.api.memory_sleep import _validate_plan_header

        candidate_id = uuid.uuid4()
        sleep_session = MagicMock()
        sleep_session.id = uuid.uuid4()
        sleep_session.candidate_memory_ids = [str(candidate_id)]
        plan = {
            "schema_version": "memory_sleep_plan.v1",
            "session_id": str(sleep_session.id),
            "input_memory_ids": [str(candidate_id)],
            "actions": [
                {
                    "op": "keep_memory",
                    "memory_id": str(uuid.uuid4()),
                }
            ],
        }

        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_header(plan, sleep_session)

        assert exc_info.value.status_code == 400
        assert "non-input" in exc_info.value.detail

    def test_malformed_nested_action_returns_validation_error(self):
        from app.api.memory_sleep import _validate_plan_header

        candidate_id = uuid.uuid4()
        sleep_session = MagicMock()
        sleep_session.id = uuid.uuid4()
        sleep_session.candidate_memory_ids = [str(candidate_id)]
        plan = {
            "schema_version": "memory_sleep_plan.v1",
            "session_id": str(sleep_session.id),
            "input_memory_ids": [str(candidate_id)],
            "actions": [
                {
                    "op": "create_memory",
                    "client_ref": "summary",
                    "derived_from": "not-a-list",
                    "memory": {
                        "title": "Summary",
                        "content": "Summary content",
                        "type": "context",
                    },
                }
            ],
        }

        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_header(plan, sleep_session)

        assert exc_info.value.status_code == 400
        assert "must be a list" in exc_info.value.detail

    def test_v2_requires_one_terminal_action_per_input(self):
        from app.api.memory_sleep import _validate_plan_header

        memories = [_make_memory("Git workflow"), _make_memory("Git branches")]
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id="user",
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id) for memory in memories],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, memories)
        plan["actions"] = plan["actions"][:-1]

        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_header(plan, sleep_session)

        assert exc_info.value.status_code == 400
        assert "terminal action" in exc_info.value.detail

    def test_v2_simulation_passes_without_rewriting_sources(self):
        from app.api.memory_sleep import _validate_plan_header
        from app.services.memory_sleep_simulation import simulate_sleep_plan_v2

        memories = [
            _make_memory("Git workflow pull requests"),
            _make_memory("Git workflow branches"),
        ]
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id="user",
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id) for memory in memories],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, memories)

        _validate_plan_header(plan, sleep_session)
        simulation = simulate_sleep_plan_v2(memories, plan)

        assert simulation["passed"] is True
        assert simulation["source_coverage"] == 1.0
        assert simulation["replay_regressions"] == 0
        assert simulation["after_token_footprint"] < simulation["before_token_footprint"]
        assert all(memory.status == "active" for memory in memories)

    def test_v2_simulation_detects_changed_precondition(self):
        from app.services.memory_sleep_simulation import simulate_sleep_plan_v2

        memories = [_make_memory("Git workflow")]
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id="user",
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memories[0].id)],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, memories)
        memories[0].status = "ai_review"

        simulation = simulate_sleep_plan_v2(memories, plan)

        assert simulation["passed"] is False
        assert any("precondition_status_changed" in item for item in simulation["failures"])

    def test_v2_token_growth_gate_uses_unrounded_ratio(self, monkeypatch):
        from app.services.memory_sleep_simulation import simulate_sleep_plan_v2

        memory = _make_memory("Git workflow")
        memory.token_count = 2009
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id="user",
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id)],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, [memory])
        monkeypatch.setattr(
            "app.services.memory_sleep_simulation.count_tokens",
            lambda _content: 2210,
        )

        simulation = simulate_sleep_plan_v2([memory], plan)

        assert simulation["token_growth_ratio"] == 0.1
        assert simulation["passed"] is False
        assert "token_growth_gate_failed" in simulation["failures"]

    def test_v2_rejects_weaker_client_quality_gates(self):
        from app.api.memory_sleep import _validate_plan_header

        memory = _make_memory("Git workflow")
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id="user",
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id)],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, [memory])
        plan["quality_gates"] = {"max_replay_regressions": 1}

        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_header(plan, sleep_session)

        assert exc_info.value.status_code == 400
        assert "out of range" in exc_info.value.detail

    def test_v2_needs_human_plan_remains_non_applicable(self):
        from app.services.memory_sleep_simulation import simulate_sleep_plan_v2

        memory = _make_memory("Git workflow")
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id="user",
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id)],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, [memory])
        plan["actions"] = [
            {
                "op": "needs_human",
                "memory_id": str(memory.id),
                "reason": "conflict",
            }
        ]

        simulation = simulate_sleep_plan_v2([memory], plan)

        assert simulation["passed"] is False
        assert "needs_human_unresolved" in simulation["failures"]


class TestSleepApply:
    """Tests for post-commit work triggered by an applied plan."""

    @pytest.mark.asyncio
    async def test_sleep_session_write_path_uses_row_lock(self, test_user_id: str):
        from app.api.memory_sleep import _get_sleep_session

        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id=test_user_id,
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[],
            created_by={"actor": "test"},
        )
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = sleep_session
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=query_result)

        result = await _get_sleep_session(
            mock_session,
            sleep_session.id,
            test_user_id,
            lock=True,
        )

        statement = mock_session.execute.await_args.args[0]
        assert result is sleep_session
        assert "FOR UPDATE" in str(statement)

    @pytest.mark.asyncio
    async def test_created_memory_schedules_embedding(self, test_user_id: str):
        from app.api.memory_sleep import (
            _compute_and_store_embedding,
            apply_sleep_proposal,
        )
        from app.schemas.sleep import SleepApplyRequest

        sleep_session_id = uuid.uuid4()
        source_id = uuid.uuid4()
        sleep_session = SleepSession(
            id=sleep_session_id,
            user_id=test_user_id,
            status="proposed",
            mode="client_generated",
            candidate_memory_ids=[str(source_id)],
            json_proposal={
                "schema_version": "memory_sleep_plan.v1",
                "session_id": str(sleep_session_id),
                "input_memory_ids": [str(source_id)],
                "actions": [
                    {
                        "op": "create_memory",
                        "client_ref": "distilled-1",
                        "derived_from": [str(source_id)],
                        "memory": {
                            "title": "Distilled title",
                            "content": "Distilled content",
                            "type": "context",
                            "scope": {
                                "global": False,
                                "projects": ["qzhqzh/EchoMe"],
                                "exclude_projects": [],
                            },
                        },
                    }
                ],
            },
            created_by={"actor": "test"},
        )
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = sleep_session
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=query_result)

        def add_with_id(obj):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=add_with_id)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        background_tasks = MagicMock()

        result = await apply_sleep_proposal(
            session_id=sleep_session_id,
            body=SleepApplyRequest(approved=True),
            background_tasks=background_tasks,
            session=mock_session,
            user_id=test_user_id,
        )

        assert len(result.created_memory_ids) == 1
        background_tasks.add_task.assert_called_once_with(
            _compute_and_store_embedding,
            result.created_memory_ids[0],
            "Distilled title\nDistilled content",
        )

    @pytest.mark.asyncio
    async def test_v2_apply_stops_before_mutation_when_simulation_fails(
        self, test_user_id: str, monkeypatch
    ):
        from app.api.memory_sleep import apply_sleep_proposal
        from app.schemas.sleep import SleepApplyRequest

        memory = _make_memory("Git workflow")
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id=test_user_id,
            status="proposed",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id)],
            created_by={"actor": "test"},
        )
        sleep_session.json_proposal = _v2_plan(sleep_session, [memory])
        get_session = AsyncMock(return_value=sleep_session)
        monkeypatch.setattr(
            "app.api.memory_sleep._get_sleep_session",
            get_session,
        )
        simulation = AsyncMock(return_value={"passed": False, "failures": ["stale"]})
        monkeypatch.setattr(
            "app.api.memory_sleep._simulate_v2_plan",
            simulation,
        )
        mock_session = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await apply_sleep_proposal(
                session_id=sleep_session.id,
                body=SleepApplyRequest(approved=True),
                background_tasks=MagicMock(),
                session=mock_session,
                user_id=test_user_id,
            )

        assert exc_info.value.status_code == 409
        assert get_session.await_args.kwargs["lock"] is True
        assert simulation.await_args.kwargs["lock"] is True
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_v2_submit_replaces_client_simulation(self, test_user_id: str, monkeypatch):
        from app.api.memory_sleep import submit_sleep_proposal
        from app.schemas.sleep import SleepProposalSubmitRequest

        memory = _make_memory("Git workflow")
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id=test_user_id,
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id)],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, [memory])
        plan["server_simulation"] = {"passed": True, "producer": "untrusted-client"}
        trusted = {"passed": True, "producer": "hub"}
        simulation = AsyncMock(return_value=trusted)
        get_session = AsyncMock(return_value=sleep_session)
        monkeypatch.setattr(
            "app.api.memory_sleep._get_sleep_session",
            get_session,
        )
        monkeypatch.setattr("app.api.memory_sleep._simulate_v2_plan", simulation)
        mock_session = AsyncMock()

        result = await submit_sleep_proposal(
            session_id=sleep_session.id,
            body=SleepProposalSubmitRequest(json_proposal=plan),
            session=mock_session,
            user_id=test_user_id,
        )

        assert result.json_proposal is not None
        assert result.json_proposal["server_simulation"] == trusted
        assert get_session.await_args.kwargs["lock"] is True
        assert simulation.await_args.kwargs["lock"] is False
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_v2_submit_rejects_failed_simulation_without_saving(
        self, test_user_id: str, monkeypatch
    ):
        from app.api.memory_sleep import submit_sleep_proposal
        from app.schemas.sleep import SleepProposalSubmitRequest

        memory = _make_memory("Git workflow")
        sleep_session = SleepSession(
            id=uuid.uuid4(),
            user_id=test_user_id,
            status="draft",
            mode="client_generated",
            candidate_memory_ids=[str(memory.id)],
            created_by={"actor": "test"},
        )
        plan = _v2_plan(sleep_session, [memory])
        get_session = AsyncMock(return_value=sleep_session)
        monkeypatch.setattr("app.api.memory_sleep._get_sleep_session", get_session)
        monkeypatch.setattr(
            "app.api.memory_sleep._simulate_v2_plan",
            AsyncMock(return_value={"passed": False, "failures": ["regression"]}),
        )
        mock_session = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await submit_sleep_proposal(
                session_id=sleep_session.id,
                body=SleepProposalSubmitRequest(json_proposal=plan),
                session=mock_session,
                user_id=test_user_id,
            )

        assert exc_info.value.status_code == 409
        assert get_session.await_args.kwargs["lock"] is True
        assert sleep_session.status == "draft"
        assert sleep_session.json_proposal is None
        mock_session.commit.assert_not_awaited()
