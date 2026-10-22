"""Real PostgreSQL discovery checks in the existing disposable-schema fixture."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.models.knowledge import KnowledgeRecord
from app.models.scene_knowledge import SceneKnowledge, SceneKnowledgeEntry
from app.services.knowledge_context import discover_knowledge_refs

pytestmark = pytest.mark.asyncio


def record(
    user_id: str, *, kind: str = "entity", status: str = "active", **data: Any
) -> KnowledgeRecord:
    return KnowledgeRecord(
        id=uuid4(),
        user_id=user_id,
        kind=kind,
        status=status,
        revision=1,
        payload={"status": status, **data},
    )


async def test_owner_archival_chinese_discovery_and_bounded_long_documents(database, test_user_id):
    own = record(test_user_id, name="规则分流策略", summary="按网络条件匹配出口")
    other = record("another-owner", name="规则分流其他人的经验")
    archived = record(test_user_id, name="规则分流旧方案", status="archived")
    merged = record(test_user_id, name="规则分流已合并", status="merged")
    long_page = record(
        test_user_id,
        kind="page",
        title="调试详情",
        body_md="背景说明。" * 20000 + "规则分流",
    )
    async with database() as session:
        session.add_all([own, other, archived, merged, long_page])
        await session.commit()
        refs = await discover_knowledge_refs(session, user_id=test_user_id, query="规则分流")
    assert {item["id"] for item in refs} == {str(own.id), str(long_page.id)}
    for item in refs:
        assert item["source"] == "knowledge"
        assert item["needs_expansion"] is True
        assert item["review_state"] == "unchecked"
        assert len(item["title"]) <= 160
        assert len(item["snippet"]) <= 240
        assert "content" not in item and "body_md" not in item
        assert item["read"]["arguments"]["data"] == {"revision": 1}


async def test_scene_owner_project_scope_archival_and_evidence(database, test_user_id):
    now = datetime.now(UTC)
    global_scene = SceneKnowledge(
        id=uuid4(),
        user_id=test_user_id,
        slug="global-network",
        title="全局网络",
        aliases=["规则分流"],
    )
    scoped_scene = SceneKnowledge(
        id=uuid4(),
        user_id=test_user_id,
        slug="project-network",
        title="项目网络",
        project_id="resolved-project",
        aliases=["规则分流"],
    )
    unrelated = SceneKnowledge(
        id=uuid4(),
        user_id=test_user_id,
        slug="another-network",
        title="其他网络",
        project_id="another-project",
        aliases=["规则分流"],
    )
    archived = SceneKnowledge(
        id=uuid4(),
        user_id=test_user_id,
        slug="old-network",
        title="归档网络",
        status="archived",
        aliases=["规则分流"],
    )
    other = SceneKnowledge(
        id=uuid4(),
        user_id="another-owner",
        slug="private-network",
        title="他人网络",
        aliases=["规则分流"],
    )
    scenes = [global_scene, scoped_scene, unrelated, archived, other]
    entries = [
        SceneKnowledgeEntry(
            id=uuid4(),
            user_id=scene.user_id,
            scene_id=scene.id,
            category="fact",
            number=1,
            content="记录的出口策略。" * 100,
            source_ref="case:network",
            evidence_at=now,
        )
        for scene in scenes
    ]
    entries.extend(
        SceneKnowledgeEntry(
            id=uuid4(),
            user_id=test_user_id,
            scene_id=global_scene.id,
            category="fact",
            number=number,
            content="不可直接复用",
            source_ref="case:network",
            status=status,
        )
        for number, status in [(2, "needs_review"), (3, "archived")]
    )
    async with database() as session:
        session.add_all(scenes)
        await session.flush()
        session.add_all(entries)
        await session.commit()
        no_project = await discover_knowledge_refs(session, user_id=test_user_id, query="规则分流")
        resolved = await discover_knowledge_refs(
            session,
            user_id=test_user_id,
            query="规则分流",
            project_id="resolved-project",
        )
    assert {item["id"] for item in no_project} == {str(entries[0].id)}
    assert {item["id"] for item in resolved} == {str(entries[0].id), str(entries[1].id)}
    for item in resolved:
        assert item["source"] == "scene"
        assert item["kind"] == "scene_entry" and item["status"] == "active"
        assert item["needs_expansion"] is True
        assert item["source_ref"] == "case:network"
        assert item["evidence_at"] == now.isoformat()
        assert len(item["snippet"]) == 240
        assert item["read"]["tool"] == "echome_scene_read"


async def test_combined_discovery_limit_is_four(database, test_user_id):
    async with database() as session:
        session.add_all(record(test_user_id, name=f"Blender technique {i}") for i in range(10))
        scene = SceneKnowledge(
            id=uuid4(),
            user_id=test_user_id,
            slug="blender",
            title="Blender practice",
        )
        session.add(scene)
        await session.flush()
        session.add_all(
            SceneKnowledgeEntry(
                user_id=test_user_id,
                scene_id=scene.id,
                category="observation",
                number=i + 1,
                content=f"Blender practice result {i}",
                source_ref="case:blender",
            )
            for i in range(10)
        )
        await session.commit()
        refs = await discover_knowledge_refs(
            session, user_id=test_user_id, query="Blender", limit=1000
        )
    assert len(refs) == 4
    assert len({item["id"] for item in refs}) == 4


async def test_current_disputed_reviews_are_visible_without_graph_expansion(
    api, database, test_user_id, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-discovery-review")
    async def create(kind: str, **data: Any) -> dict[str, Any]:
        response = await api.post("knowledge/records", json={"kind": kind, "data": data})
        assert response.status_code == 201, response.text
        return response.json()

    entity = await create("entity", name="Blender procedure")
    review = await create(
        "review",
        title="Needs checking",
        issue_kind="overgeneralization",
        explanation="Only one trial",
        targets=[{"id": entity["id"], "revision": 1}],
    )
    async with database() as session:
        refs = await discover_knowledge_refs(session, user_id=test_user_id, query="Blender")
    assert refs[0]["review_state"] == "disputed"
    dismissed = await api.patch(
        f"knowledge/records/{review['id']}",
        headers={"X-EchoMe-Review-Key": "test-discovery-review"},
        json={"expected_revision": 1, "data": {**review["data"], "status": "dismissed"}},
    )
    assert dismissed.status_code == 200, dismissed.text
    async with database() as session:
        refs = await discover_knowledge_refs(session, user_id=test_user_id, query="Blender")
    assert refs[0]["review_state"] == "unchecked"
