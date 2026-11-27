"""Shared personal-memory retrieval tests."""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.memory import Memory
from app.schemas.retrieval_debug import RetrievalLogCreate
from app.services.memory_retrieval import (
    lexical_memory_similarity,
    memory_query_tokens,
    retrieve_memories,
)


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


def test_git_aliases_require_a_complete_latin_term() -> None:
    assert "workflow" not in memory_query_tokens("digital illustration")
    assert "workflow" in memory_query_tokens("Git提交流程")


@pytest.mark.parametrize("field", ["title", "tags", "content"])
def test_latin_short_terms_do_not_match_inside_other_words(field: str) -> None:
    fields = {"title": "", "tags": [], "content": ""}
    text = "CattleDBItem Variant detail expanded annotation tables; email previews"
    fields[field] = [text] if field == "tags" else text
    assert lexical_memory_similarity({"ai", "pr"}, **fields) == 0.0


@pytest.mark.parametrize(
    ("token", "title"),
    [
        ("ai", "AI-assisted illustration"),
        ("wg", "配置WG网络"),
        ("c++", "C++ API"),
        ("c#", "C# 开发"),
        ("foo_bar", "foo_bar"),
        ("10.0.1.2", "连接10.0.1.2"),
    ],
)
def test_latin_boundaries_preserve_technical_terms(token: str, title: str) -> None:
    assert lexical_memory_similarity({token}, title=title, tags=[], content="") == 0.45


def test_specific_task_requires_more_than_broad_ai_or_conversational_words() -> None:
    tokens = set(memory_query_tokens("AI 如何用 Blender 构建 3D 鲸鱼娘？"))
    assert (
        lexical_memory_similarity(
            tokens, title="网站用模块级精修替代 AI 一次成站", tags=["ai"], content=""
        )
        == 0.0
    )
    assert (
        lexical_memory_similarity(
            tokens, title="三维教学模型采用结构级聚焦", tags=["3d"], content=""
        )
        == 0.35
    )
    assert (
        lexical_memory_similarity(
            set(memory_query_tokens("在我们的网络与基础设施领域，查询规则分流知识")),
            title="代码审查",
            tags=[],
            content="我们的知识和一个相关项目",
        )
        == 0.0
    )
    # A broad word remains useful when it is the actual subject of the query.
    assert lexical_memory_similarity({"ai"}, title="AI 创作", tags=[], content="") == 0.45


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("与基础设施", 0.18),
        ("与基础设施；与基础设施", 0.18),
        ("基础设施和网络", 0.36),
        ("git workflow", 0.36),
    ],
)
def test_overlapping_body_ngrams_are_one_signal_and_separate_terms_still_count(
    content: str, expected: float
) -> None:
    assert (
        lexical_memory_similarity(
            {"基础设施", "与基", "网络", "git", "workflow"},
            title="",
            tags=[],
            content=content,
        )
        == expected
    )


@pytest.mark.asyncio
async def test_sql_lexical_candidates_use_the_same_literal_word_boundaries() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_count_result(0), _scalar_result([])])
    with patch("app.services.memory_retrieval.get_embedding", return_value=None):
        await retrieve_memories(session, user_id="user", query="foo_bar c++", limit=5)
    statement = session.execute.await_args_list[1].args[0]
    sql = str(statement.compile())
    params = statement.compile().params.values()
    assert " ~ " in sql
    assert r"(^|[^a-z0-9_])foo_bar($|[^a-z0-9_])" in params
    assert r"(^|[^a-z0-9_])c\+\+($|[^a-z0-9_])" in params
    assert "%foo_bar%" not in params


@pytest.mark.asyncio
async def test_weak_vectors_require_specific_lexical_support_on_the_recalled_union() -> None:
    detail = _memory("CattleDBItem Variant detail expanded annotation tables", "Other page")
    broad_ai = _memory("网站用模块级精修替代 AI 一次成站", "Web pages")
    model = _memory("三维教学模型采用结构级聚焦", "教学呈现", tags=["3d"])
    paraphrase = _memory("立体角色制作流程", "先做轮廓再调整拓扑")
    vector_rows = [
        (detail, 1 - 0.463),
        (broad_ai, 1 - 0.4667),
        (model, 1 - 0.4035),
        (paraphrase, 1 - 0.5389),
    ]
    session = AsyncMock()
    # No SQL lexical candidates: vector hits still need full lexical scoring.
    session.execute = AsyncMock(side_effect=[_count_result(4), vector_rows, _scalar_result([])])
    with patch("app.services.memory_retrieval.get_embedding", return_value=[0.1] * 1024):
        result = await retrieve_memories(
            session, user_id="user", query="AI 如何用 Blender 构建 3D 鲸鱼娘？", limit=5
        )

    assert [item.memory.id for item in result.items] == [model.id, paraphrase.id]
    assert result.items[0].reasons == ("vector", "lexical")
    assert result.items[1].reasons == ("vector",)
    assert result.trace["weak_vector_only_filtered"] == 2
    assert result.trace["lexical_candidate_count"] == 0
    assert result.trace["lexical_count"] == 1
    assert result.trace["min_vector_only_score"] == 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("min_score", "similarity", "expected"),
    [
        (0.3, 0.3979, False),
        (0.3, 0.5, True),
        (0.3, 0.5389, True),
        (0.6, 0.5389, False),
        (0.2, 0.3979, True),
    ],
)
async def test_vector_only_admission_keeps_semantic_matches_and_explicit_broad_search(
    min_score: float, similarity: float, expected: bool
) -> None:
    memory = _memory("VPS 隧道设备配置", "通过二维码导入连接")
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _count_result(1),
            [(memory, 1 - similarity)],
            _scalar_result([]),
        ]
    )
    with patch("app.services.memory_retrieval.get_embedding", return_value=[0.1] * 1024):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="外面怎么连回我家里的服务？",
            limit=5,
            min_source_score=min_score,
        )
    assert bool(result.items) is expected
    if expected:
        assert result.items[0].reasons == ("vector",)


@pytest.mark.asyncio
async def test_zero_threshold_never_makes_an_unmatched_sql_candidate_lexical_evidence() -> None:
    memory = _memory("Unrelated note", "A different subject")
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_count_result(1), _scalar_result([memory])])
    with patch("app.services.memory_retrieval.get_embedding", return_value=None):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="Blender",
            limit=5,
            min_source_score=0,
        )
    assert result.items == []


@pytest.mark.asyncio
async def test_lexical_retrieval_understands_common_project_phrasing() -> None:
    workflow = _memory(
        "Git workflow",
        "All repository changes go through a pull request before merge.",
        tags=["git", "policy"],
    )
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_count_result(1), _scalar_result([workflow])])

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
    session.execute = AsyncMock(side_effect=[_count_result(1), _scalar_result([workflow])])

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
async def test_sensitive_query_is_never_sent_to_embedding_service() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_count_result(0), _scalar_result([])])
    embedding = AsyncMock()

    with patch("app.services.memory_retrieval.get_embedding", new=embedding):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="password=" + "V3ry-Private-Password-9081",
            limit=5,
        )

    embedding.assert_not_awaited()
    assert result.trace["sensitive_query_embedding_skipped"] is True


@pytest.mark.asyncio
async def test_bearer_query_is_never_sent_to_embedding_service() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_count_result(0), _scalar_result([])])
    embedding = AsyncMock()

    with patch("app.services.memory_retrieval.get_embedding", new=embedding):
        result = await retrieve_memories(
            session,
            user_id="user",
            query="Authorization: Bearer " + "prodTokenABC1234567890",
            limit=5,
        )

    embedding.assert_not_awaited()
    assert result.trace["sensitive_query_embedding_skipped"] is True


@pytest.mark.asyncio
async def test_default_query_filters_active_and_ai_review_in_sql() -> None:
    active = _memory("Active policy", "git workflow", status="active")
    review = _memory("Review policy", "git workflow", status="ai_review")
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_count_result(2), _scalar_result([active, review])])

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
    lexical_compiled = str(lexical_statement.compile(compile_kwargs={"literal_binds": True}))
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
    session.execute = AsyncMock(side_effect=[_count_result(1), _scalar_result([workflow])])

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
