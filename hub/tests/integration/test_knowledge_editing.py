"""Human capture is atomic; choice lists remain bounded and scoped to the owner."""

import asyncio
from uuid import uuid4

import pytest

from app.core.jwt import create_access_token
from app.models import User

pytestmark = pytest.mark.asyncio


async def create(api, kind, **data):
    response = await api.post("knowledge/records", json={"kind": kind, "data": data})
    assert response.status_code == 201, response.text
    return response.json()


async def test_capture_project_question_and_classification_are_atomic(api):
    project_response = await api.post(
        "knowledge/capture",
        json={
            "record": {"kind": "project", "data": {"name": "First project"}},
            "first_question": "What do I need to learn?",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    question_id = project["created"]["question_id"]
    question = (await api.get(f"knowledge/records/{question_id}")).json()
    assert question["data"]["project_id"] == project["record"]["id"]
    domain_response = await api.post(
        "knowledge/capture",
        json={
            "record": {"kind": "entity", "data": {"name": "Research", "entity_kind": "topic"}},
            "placement": {"parent_id": None},
        },
    )
    assert domain_response.status_code == 201, domain_response.text
    domain = domain_response.json()
    assert (await api.get("knowledge/directory")).json()["items"][0]["entity_id"] == domain[
        "record"
    ]["id"]
    captured_response = await api.post(
        "knowledge/capture",
        json={
            "record": {
                "kind": "entity",
                "data": {"name": "Evidence method", "entity_kind": "method"},
            },
            "placement": {"parent_id": domain["created"]["placement_id"]},
            "context_id": question_id,
        },
    )
    assert captured_response.status_code == 201, captured_response.text
    captured = captured_response.json()
    uses = (
        await api.post(
            "knowledge/query", json={"kind": "usage", "filters": {"context_id": question_id}}
        )
    ).json()
    assert (
        uses["total"] == 1 and uses["items"][0]["data"]["knowledge_id"] == captured["record"]["id"]
    )
    assert (
        uses["items"][0]["data"]["knowledge_revision"] == 1
        and uses["items"][0]["data"]["role"] == "to_research"
    )
    failed = await api.post(
        "knowledge/capture",
        json={
            "record": {"kind": "entity", "data": {"name": "Must roll back"}},
            "placement": {"parent_id": str(uuid4())},
        },
    )
    assert failed.status_code == 404
    assert (
        await api.get("knowledge/records", params={"kind": "entity", "search": "Must roll back"})
    ).json()["total"] == 0
    assert (
        await api.post(
            "knowledge/capture",
            json={
                "record": {"kind": "question", "data": {"title": "Invalid classification"}},
                "placement": {"parent_id": None},
            },
        )
    ).status_code == 422


async def test_choices_pagination_search_paths_and_private_capture(api, database):
    roots = [
        await create(api, "entity", name=name, entity_kind="topic")
        for name in ("Design", "Science")
    ]
    positions = [await create(api, "placement", entity_id=root["id"]) for root in roots]
    for parent in positions:
        topic = await create(api, "entity", name="Methods", entity_kind="topic")
        await create(api, "placement", entity_id=topic["id"], parent_id=parent["id"])
    response = await api.get(
        "knowledge/choices", params={"kinds": "placement", "search": "Methods", "limit": 1}
    )
    assert response.status_code == 200, response.text
    first = response.json()
    second = (
        await api.get(
            "knowledge/choices",
            params={"kinds": "placement", "search": "Methods", "limit": 1, "offset": 1},
        )
    ).json()
    assert first["total"] == 2 and first["next_offset"] == 1 and second["next_offset"] is None
    assert {
        tuple(node["name"] for node in item["path"]["nodes"])
        for item in [*first["items"], *second["items"]]
    } == {("Design", "Methods"), ("Science", "Methods")}
    created = [
        await create(api, "entity", name=f"Method {index:02d}", entity_kind="method")
        for index in range(23)
    ]
    choices = (
        await api.get(
            "knowledge/choices",
            params={"kinds": "entity,relation", "exclude_topics": True, "limit": 20},
        )
    ).json()
    assert choices["total"] == 23 and len(choices["items"]) == 20 and choices["next_offset"] == 20
    tail = (
        await api.get(
            "knowledge/choices",
            params={"kinds": "entity,relation", "exclude_topics": True, "offset": 20},
        )
    ).json()
    assert len(tail["items"]) == 3 and tail["next_offset"] is None
    found = (
        await api.get("knowledge/choices", params={"kinds": "entity", "search": "Method 22"})
    ).json()
    assert found["total"] == 1 and found["items"][0]["id"] == created[-1]["id"]
    user_id = uuid4()
    async with database() as session:
        session.add(User(id=user_id, github_id=760555, username="editing-other"))
        await session.commit()
    headers = {
        "Authorization": "Bearer " + create_access_token(user_id, "editing-other", "user")[0]
    }
    assert (
        await api.get("knowledge/choices", params={"kinds": "placement"}, headers=headers)
    ).json()["total"] == 0
    blocked = await api.post(
        "knowledge/capture",
        headers=headers,
        json={
            "record": {"kind": "entity", "data": {"name": "Private location"}},
            "placement": {"parent_id": positions[0]["id"]},
        },
    )
    assert blocked.status_code == 404
    assert (await api.get("knowledge/records", params={"kind": "entity"}, headers=headers)).json()[
        "total"
    ] == 0
    assert (await api.get("knowledge/choices", params={"kinds": "unknown"})).status_code == 422


async def test_remove_classification_preserves_knowledge_and_serializes_children(api):
    topic = await create(api, "entity", name="Domain", entity_kind="topic")
    knowledge = await create(api, "entity", name="Method", entity_kind="method")
    root = await create(api, "placement", entity_id=topic["id"])
    leaf = await create(api, "placement", entity_id=knowledge["id"], parent_id=root["id"])
    question = await create(api, "question", title="Use the method")
    usage = await create(
        api,
        "usage",
        context_id=question["id"],
        knowledge_id=knowledge["id"],
        knowledge_revision=1,
    )
    blocked = await api.post(
        f"knowledge/placements/{root['id']}/remove", json={"expected_revision": 1}
    )
    assert blocked.status_code == 409 and "active children" in blocked.text
    stale = await api.post(
        f"knowledge/placements/{leaf['id']}/remove", json={"expected_revision": 2}
    )
    assert stale.status_code == 409
    removed = await api.post(
        f"knowledge/placements/{leaf['id']}/remove", json={"expected_revision": 1}
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "archived" and removed.json()["revision"] == 2
    assert (await api.get(f"knowledge/records/{knowledge['id']}")).json()["status"] == "active"
    assert (await api.get(f"knowledge/records/{usage['id']}")).json()["data"][
        "knowledge_revision"
    ] == 1
    assert (await api.get(f"knowledge/records/{leaf['id']}/history")).json()["total"] == 2

    # Either the new child wins and removal is rejected, or removal wins and the
    # child cannot be inserted below an inactive parent. Both must not succeed.
    removal, addition = await asyncio.gather(
        api.post(f"knowledge/placements/{root['id']}/remove", json={"expected_revision": 1}),
        api.post(
            "knowledge/records",
            json={
                "kind": "placement",
                "data": {"entity_id": knowledge["id"], "parent_id": root["id"]},
            },
        ),
    )
    assert (removal.status_code, addition.status_code) in {(200, 422), (409, 201)}, (
        removal.text,
        addition.text,
    )
    final_root = (await api.get(f"knowledge/records/{root['id']}")).json()
    if addition.status_code == 201:
        assert final_root["status"] == "active"
    else:
        assert final_root["status"] == "archived"
