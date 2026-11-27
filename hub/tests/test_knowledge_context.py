"""Discovery remains bounded and does not fetch entire knowledge documents."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, func, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import BinaryExpression

from app.services.discovery_query import discovery_query_tokens
from app.services.knowledge_context import (
    _discovery_match,
    _overview_requested,
    discover_knowledge_refs,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?! % _", "123 456", "如何", "知识", "the and for"])
async def test_empty_or_generic_discovery_never_queries_database(query: str) -> None:
    session = AsyncMock()
    assert await discover_knowledge_refs(session, user_id="owner", query=query) == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id", [None, "resolved-project"])
async def test_discovery_uses_two_owner_scoped_bounded_projections(project_id: str | None) -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result
    await discover_knowledge_refs(
        session,
        user_id="owner",
        query=" ".join(f"token{number}" for number in range(100)),
        project_id=project_id,
        limit=1000,
    )
    assert session.execute.await_count == 2
    statements = [call.args[0] for call in session.execute.await_args_list]
    sql = [
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in statements
    ]
    assert all("LIMIT 4" in statement for statement in sql)
    assert all("left(" in statement for statement in sql)
    assert "knowledge_records.user_id = 'owner'" in sql[0]
    assert "scene_knowledge.user_id = 'owner'" in sql[1]
    assert "scene_knowledge_entries.user_id = 'owner'" in sql[1]
    assert "scene_knowledge.project_id IS NULL" in sql[1]
    assert ("scene_knowledge.project_id = 'resolved-project'" in sql[1]) == bool(project_id)
    assert "knowledge_references.owner_revision = knowledge_records_1.revision" in sql[0]
    for statement in statements:
        assert "payload" not in statement.selected_columns
        assert "content" not in statement.selected_columns
        patterns = {
            value
            for value in statement.compile().params.values()
            if isinstance(value, str) and (value.startswith("%") or value.startswith(r"\m"))
        }
        assert 0 < len(patterns) <= 24


@pytest.mark.asyncio
async def test_disabled_discovery_never_queries_database() -> None:
    session = AsyncMock()
    assert await discover_knowledge_refs(session, user_id="owner", query="Blender", limit=0) == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_broad_multiword_tokens_are_removed_and_short_term_regex_is_bounded() -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result
    await discover_knowledge_refs(
        session,
        user_id="owner",
        query="AI 模型 甲乙 丙丁 戊己 庚辛 壬癸 子丑 寅卯 辰巳 午未 申酉 戌亥",
    )
    for call in session.execute.await_args_list:
        params = call.args[0].compile().params.values()
        strings = [value for value in params if isinstance(value, str)]
        assert r"\mai\M" not in strings
        assert "%模型%" not in strings
        proximity = [value for value in strings if value.startswith("(?s)")]
        assert len(proximity) == 1
        assert proximity[0].count("|") <= 55  # Eight terms, at most 28 bidirectional pairs.


def _candidate(
    identity: str, *, rank: int, scene_id: str | None = None, entry_rank: int = 0,
    days_old: int = 0,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": identity, "kind": "page", "revision": 2, "status": "active",
        "updated_at": datetime(2026, 10, 29, tzinfo=timezone.utc) - timedelta(days=days_old),
        "title": "家庭网络架构", "snippet": "具体内容需展开；保留来源及当前警示。",
        "disputed": False, "rank": rank,
    }
    if scene_id is not None:
        row.update({
            "scene_id": scene_id, "slug": "home-network", "category": "fact",
            "source_ref": "network-access/office-243", "evidence_at": row["updated_at"],
            "entry_rank": entry_rank,
        })
    return row


def _candidate_session(knowledge: list[dict], scenes: list[dict]) -> AsyncMock:
    result_sets = []
    for rows in (knowledge, scenes):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        result_sets.append(result)
    session = AsyncMock()
    session.execute.side_effect = result_sets
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("discovery", [False, True])
async def test_auto_scene_diversity_keeps_relevant_architecture_page_without_changing_explicit_reads(
    discovery: bool,
) -> None:
    page = _candidate("architecture-page", rank=2, days_old=30)
    scenes = [_candidate(f"entry-{index}", rank=5, scene_id="same-scene") for index in range(4)]
    session = _candidate_session([page], scenes)

    result = await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络 FlClash", discovery=discovery,
    )

    if discovery:
        assert len([item for item in result if item["source"] == "scene"]) == 2
        assert "architecture-page" in {item["id"] for item in result}
        assert len(result) == 3  # Do not refill the fourth slot with a third copy of the same scene.
        assert next(item for item in result if item["source"] == "knowledge")["read"]["arguments"] == {
            "action": "get", "record_id": "architecture-page", "data": {"revision": 2}, "view": "full",
        }
        for item in result:
            if item["source"] == "scene":
                assert item["read"]["arguments"]["entry_id"] == item["id"]
                assert item["read"]["arguments"]["view"] == "compact"
                assert item["needs_expansion"] is True
                assert item["source_ref"] == "network-access/office-243"
    else:
        assert [item["id"] for item in result] == [f"entry-{index}" for index in range(4)]
        assert all("entry_id" not in item["read"]["arguments"] for item in result)


@pytest.mark.asyncio
async def test_auto_discovery_preserves_a_strong_page_among_different_scenes() -> None:
    page = _candidate("architecture-page", rank=2, days_old=30)
    scenes = [
        _candidate(f"entry-{index}", rank=5, scene_id=f"scene-{index}") for index in range(4)
    ]
    session = _candidate_session([page], scenes)

    result = await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络 FlClash", discovery=True,
    )

    assert len(result) == 4
    assert "architecture-page" in {item["id"] for item in result}
    assert len([item for item in result if item["source"] == "scene"]) == 3


@pytest.mark.asyncio
async def test_auto_discovery_does_not_reserve_a_slot_for_a_weak_source() -> None:
    weak_page = _candidate("weak-neighbor-page", rank=1)
    scenes = [
        _candidate(f"entry-{index}", rank=5, scene_id=f"scene-{index}") for index in range(4)
    ]
    session = _candidate_session([weak_page], scenes)

    result = await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络 FlClash", discovery=True,
    )

    assert len(result) == 4
    assert "weak-neighbor-page" not in {item["id"] for item in result}


@pytest.mark.asyncio
async def test_auto_scene_selection_prefers_entry_specific_device_evidence_to_recency() -> None:
    # All rows share the same scene title match. The older office entry has
    # the independent identifier/content match, unlike newer unrelated devices.
    scenes = [
        _candidate("new-unrelated-device", rank=5, scene_id="network", entry_rank=0),
        _candidate("office-243", rank=5, scene_id="network", entry_rank=3, days_old=30),
        _candidate("new-general-note", rank=5, scene_id="network", entry_rank=0),
    ]
    session = _candidate_session([], scenes)

    result = await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络办公电脑 243 FlClash", discovery=True, limit=1,
    )

    assert [item["id"] for item in result] == ["office-243"]
    scene_statement = session.execute.await_args_list[1].args[0]
    compiled = scene_statement.compile(dialect=postgresql.dialect())
    assert "entry_rank" in scene_statement.selected_columns
    assert r"\m243\M" in compiled.params.values()
    # The candidate query itself also ranks content evidence before recency,
    # otherwise the desired older row could disappear before diversification.
    order_by = str(compiled).split("ORDER BY", 1)[1]
    assert "scene_knowledge_entries.content" in order_by.split("scene_knowledge_entries.updated_at")[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,expected", [(1, 3), (2, 6), (4, 12), (1000, 12)])
async def test_auto_discovery_candidate_pools_stay_bounded(limit: int, expected: int) -> None:
    session = _candidate_session([], [])

    await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络 FlClash", discovery=True, limit=limit,
    )

    assert session.execute.await_count == 2
    for call in session.execute.await_args_list:
        compiled = call.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        )
        assert f"LIMIT {expected}" in str(compiled)


@pytest.mark.asyncio
async def test_auto_knowledge_diversity_preserves_dispute_warning_and_revision() -> None:
    disputed = _candidate("disputed-page", rank=5)
    disputed["disputed"] = True
    session = _candidate_session([disputed], [_candidate("scene", rank=5, scene_id="network")])

    result = await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络 FlClash", discovery=True,
    )

    page = next(item for item in result if item["id"] == "disputed-page")
    assert page["review_state"] == "disputed"
    assert page["needs_expansion"] is True
    assert page["revision"] == 2
    assert page["read"]["arguments"]["data"]["revision"] == 2


@pytest.mark.parametrize(
    "query,title,body,expected",
    [
        ("安装 IGV 并发布到 ACR", "图序交付说明", "提供安装包和发布说明。", False),
        ("转录本 外显子总数", "其他资料", "这里只提到转录本。", False),
        ("转录本 外显子总数", "生信资料", "这里记录转录本的外显子总数。", True),
        ("WDL OSS 挂载映射", "安装手册", "提供挂载映射和安装路径。", False),
        ("WDL OSS 挂载映射", "安装手册", "WDL 使用这里的挂载映射。", True),
        ("了解家庭网络 FlClash VPN", "家庭网络架构", "wg0 / wg1 接入与出口。", True),
        ("bycrm.qzhqzh.com 域名", "域名与证书", "其他项目的证书运维。", False),
        ("FlClash 配置", "家庭网络", "该设备使用 FlClash 接入。", True),
        ("FlClash VPN 掉线", "工具说明", "Windows 安装说明。", False),
        ("排查 243 掉线", "网络设备", "设备 243 的归属和接入情况。", True),
    ],
)
def test_auto_topic_admission_uses_independent_evidence_without_losing_named_tools(
    query: str, title: str, body: str, expected: bool,
) -> None:
    matched, _, _, _ = _discovery_match(
        literal(title), literal(""), literal(body), query, discovery_query_tokens(query)[:24],
    )

    def sqlite_regex(node: Any) -> Any:
        if isinstance(node, BinaryExpression) and getattr(node.operator, "opstring", None) == "~*":
            return func.pg_regex(node.left, node.right)
        return None

    # Evaluate the real admission expression with an in-memory regex adapter;
    # no database service, production rows, or duplicate Python scorer is needed.
    expression = visitors.replacement_traverse(matched, {}, sqlite_regex)
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.connection.driver_connection.create_function(
            "pg_regex", 2,
            lambda value, pattern: bool(re.search(
                pattern.replace(r"\m", r"(?<!\w)").replace(r"\M", r"(?!\w)"),
                value or "", re.I,
            )),
        )
        assert bool(connection.scalar(select(expression))) is expected
    engine.dispose()


@pytest.mark.asyncio
async def test_auto_knowledge_content_coverage_beats_newer_single_topic_page() -> None:
    older = _candidate("architecture-context", rank=5, days_old=30)
    older["content_rank"] = 3
    newer = _candidate("one-topic-new-note", rank=5)
    newer["content_rank"] = 1
    session = _candidate_session([newer, older], [])

    result = await discover_knowledge_refs(
        session, user_id="owner", query="家庭网络 FlClash VPN", discovery=True, limit=1,
    )

    assert [item["id"] for item in result] == ["architecture-context"]
    statement = session.execute.await_args_list[0].args[0]
    assert "content_rank" in statement.selected_columns
    order_by = str(statement.compile()).split("ORDER BY", 1)[1]
    assert "body_md" in str(statement.compile().params.values())
    assert "CASE" in order_by.split("knowledge_records.updated_at")[0]


@pytest.mark.parametrize(
    "query,expected", [("了解家庭网络，然后排查 FlClash VPN", True), ("修复 FlClash VPN 掉线", False)],
)
def test_overview_priority_only_applies_to_requested_background(query: str, expected: bool) -> None:
    assert _overview_requested(query) is expected


@pytest.mark.asyncio
async def test_related_overview_can_preserve_background_without_repeating_new_tool_names() -> None:
    overview = _candidate("existing-overview", rank=5, days_old=30)
    overview.update(overview_rank=1, content_rank=1)
    newer = _candidate("newer-debug-notes", rank=5)
    newer.update(overview_rank=0, content_rank=3)
    session = _candidate_session([newer, overview], [
        _candidate("device-detail", rank=5, scene_id="network", entry_rank=3),
    ])

    result = await discover_knowledge_refs(
        session, user_id="owner", query="了解家庭网络 FlClash VPN", discovery=True, limit=2,
    )

    assert {item["id"] for item in result} == {"existing-overview", "device-detail"}
    statement = session.execute.await_args_list[0].args[0]
    assert "overview_rank" in statement.selected_columns
    assert [{"role": "overview"}] in statement.compile().params.values()
