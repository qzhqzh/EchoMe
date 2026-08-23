"""Shared personal-memory retrieval tests."""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.memory import Memory
from app.schemas.retrieval_debug import RetrievalLogCreate
from app.services.memory_retrieval import memory_query_tokens, retrieve_memories


def _memory(
    title: str,
    content: str,
    *,
    status: str = "active",
    tags: list[str] | None = None,
) -> Memory:
    return Memory(
        id=uuid.uuid4(),
        user_id="user",
        title=title,
        content=content,
        type="context",
        layer="L1",
        scope_global=True,
        priority=7,
        tags=tags or [],
        status=status,
        updated_at=datetime.now(timezone.utc),
    )


def _scalar_result(items: list[Memory]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _count_result(total: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = total
    return result


def test_query_tokenization_is_bounded_for_long_agent_tasks() -> None:
    tokens = memory_query_tokens("架构约束" * 5000)

    assert len(tokens) <= 64
    assert all(len(token) <= 64 for token in tokens)


@pytest.mark.asyncio
async def test_lexical_retrieval_understands_common_project_phrasing() -> None:
    workflow = _memory(
        "Git workflow",
        "All repository changes go through a pull request before merge.",
        tags=["git", "policy"],
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_count_result(1), _scalar_result([workflow])]
    )

    with patch("app.services.memory_retrieval.get_embedding", return_value=None):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="Git 提交流程按什么规则？",
            limit=5,
        )

    assert [item.memory.id for item in result.items] == [workflow.id]
    assert result.items[0].reasons == ("lexical",)
    assert result.trace["vector_available"] is False


@pytest.mark.asyncio
async def test_vector_retrieval_recovers_a_paraphrased_home_network_question() -> None:
    network = _memory(
        "家庭网络拓扑",
        "入口经 EdgeOne，WireGuard 连接内部服务。",
        tags=["network"],
        status="ai_review",
    )
    vector_result = MagicMock()
    vector_result.__iter__ = MagicMock(return_value=iter([(network, 0.08)]))
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_count_result(1), vector_result, _scalar_result([network])]
    )

    with patch(
        "app.services.memory_retrieval.get_embedding",
        return_value=[0.1] * 1024,
    ):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="我的家庭网络架构是怎样？",
            limit=5,
        )

    assert result.items[0].memory.id == network.id
    assert "vector" in result.items[0].reasons
    assert result.trace["vector_available"] is True


@pytest.mark.asyncio
async def test_embedding_timeout_degrades_to_lexical_retrieval() -> None:
    workflow = _memory("Git workflow", "Use pull requests.", tags=["git"])
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_count_result(1), _scalar_result([workflow])]
    )

    async def slow_embedding(_query: str) -> None:
        await asyncio.sleep(0.02)
        return None

    with patch("app.services.memory_retrieval.get_embedding", side_effect=slow_embedding):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="Git workflow",
            limit=5,
            embedding_timeout_seconds=0.001,
        )

    assert result.items[0].memory.id == workflow.id
    assert result.trace["vector_available"] is False


@pytest.mark.asyncio
async def test_default_query_filters_active_and_ai_review_in_sql() -> None:
    active = _memory("Active policy", "git workflow", status="active")
    review = _memory("Review policy", "git workflow", status="ai_review")
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_count_result(2), _scalar_result([active, review])]
    )

    with patch("app.services.memory_retrieval.get_embedding", return_value=None):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="git workflow",
            limit=5,
        )

    statement = session.execute.await_args_list[0].args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    lexical_statement = session.execute.await_args_list[1].args[0]
    lexical_compiled = str(
        lexical_statement.compile(compile_kwargs={"literal_binds": True})
    )
    assert "active" in compiled
    assert "ai_review" in compiled
    assert "archived" not in compiled
    assert "deprecated" not in compiled
    assert "LIMIT 200" in lexical_compiled
    assert {item.memory.status for item in result.items} == {"active", "ai_review"}


@pytest.mark.asyncio
async def test_personal_context_filter_is_global_only() -> None:
    workflow = _memory("Git workflow", "Use pull requests.")
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_count_result(1), _scalar_result([workflow])]
    )

    with patch("app.services.memory_retrieval.get_embedding", return_value=None):
        await retrieve_memories(
            session,
            user_id="user",
            query="Git workflow",
            limit=5,
            global_only=True,
        )

    statement = session.execute.await_args_list[0].args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "scope_global IS true" in compiled


@pytest.mark.asyncio
async def test_retrieval_log_does_not_duplicate_memory_content() -> None:
    from app.api.retrieval_debug import _save_log

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    log = await _save_log(
        session,
        "user",
        RetrievalLogCreate(
            query="git workflow",
            top_results=[
                {
                    "id": str(uuid.uuid4()),
                    "title": "Git workflow",
                    "content": "This text remains authoritative only in memories.",
                    "memory": {"memory_content": "Nested copies are also removed."},
                    "snippet": "Alternative body keys are not accepted.",
                    "score": 0.9,
                }
            ],
            steps=[{"stage": "candidate", "payload": {"content": "do not persist"}}],
        ),
    )

    assert log.top_results[0]["title"] == "Git workflow"
    assert "content" not in log.top_results[0]
    assert "memory" not in log.top_results[0]
    assert "snippet" not in log.top_results[0]
    assert log.steps == [{"stage": "candidate"}]
