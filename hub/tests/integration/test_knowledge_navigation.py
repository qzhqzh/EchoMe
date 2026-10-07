"""Navigation must preserve ownership, shared identities, paths and complete pagination."""

from uuid import uuid4

import pytest

from app.core.jwt import create_access_token
from app.models import User

pytestmark = pytest.mark.asyncio


async def create(api, kind, **data):
    response = await api.post("knowledge/records", json={"kind": kind, "data": data})
    assert response.status_code == 201, response.text
    return response.json()


async def other_headers(database):
    user_id = uuid4()
    async with database() as session:
        session.add(User(id=user_id, github_id=897, username="navigation-other"))
        await session.commit()
    return {
        "Authorization": "Bearer " + create_access_token(user_id, "navigation-other", "user")[0]
    }


async def test_project_tree_shared_knowledge_independent_questions_and_ownership(api, database):
    projects = [await create(api, "project", name=name) for name in ("Blender", "EchoMe")]
    questions = [
        await create(api, "question", title="How to validate?", project_id=p["id"])
        for p in projects
    ]
    standalone = await create(api, "question", title="Reuse across sessions?")
    knowledge = await create(api, "entity", name="Reproducible checks", entity_kind="method")
    uses = [
        await create(
            api, "usage", context_id=q["id"], knowledge_id=knowledge["id"], knowledge_revision=1
        )
        for q in [*questions, standalone]
    ]
    direct = await create(
        api,
        "usage",
        context_id=projects[0]["id"],
        knowledge_id=knowledge["id"],
        knowledge_revision=1,
    )
    first = (await api.get("knowledge/project-tree", params={"limit": 1})).json()
    assert first["total"] == 2 and first["next_offset"] == 1 and first["independent_total"] == 1
    assert first["items"][0]["id"] == projects[0]["id"] and first["items"][0]["child_count"] == 2
    second = (await api.get("knowledge/project-tree", params={"limit": 1, "offset": 1})).json()
    assert second["items"][0]["id"] == projects[1]["id"] and second["next_offset"] is None
    branch = (
        await api.get("knowledge/project-tree", params={"parent_id": projects[0]["id"]})
    ).json()
    assert [item["id"] for item in branch["items"]] == [questions[0]["id"], knowledge["id"]]
    assert branch["items"][0]["child_count"] == 1
    assert branch["items"][1]["via_id"] == direct["id"]
    for q, use in zip([*questions, standalone], uses, strict=True):
        result = (await api.get("knowledge/project-tree", params={"parent_id": q["id"]})).json()
        assert result["items"][0]["id"] == knowledge["id"]
        assert result["items"][0]["via_id"] == use["id"]
        assert result["items"][0]["knowledge_revision"] == 1
    independent = (await api.get("knowledge/project-tree", params={"independent": True})).json()
    assert independent["total"] == 1 and independent["items"][0]["id"] == standalone["id"]
    headers = await other_headers(database)
    assert (await api.get("knowledge/project-tree", headers=headers)).json()["total"] == 0
    assert (
        await api.get(
            "knowledge/project-tree", headers=headers, params={"parent_id": projects[0]["id"]}
        )
    ).status_code == 404
    assert (
        await api.get("knowledge/project-tree", params={"parent_id": knowledge["id"]})
    ).status_code == 422


async def test_connections_trace_all_paths_and_pinned_contexts(api, database, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    root = await create(api, "entity", name="Knowledge systems", entity_kind="topic")
    root_position = await create(api, "placement", entity_id=root["id"])
    sub = await create(api, "entity", name="Organization", entity_kind="topic")
    sub_position = await create(
        api, "placement", entity_id=sub["id"], parent_id=root_position["id"]
    )
    entity = await create(api, "entity", name="Independent shared knowledge")
    await create(api, "placement", entity_id=entity["id"], parent_id=sub_position["id"])
    await create(api, "placement", entity_id=entity["id"], parent_id=root_position["id"])
    project = await create(api, "project", name="EchoMe redesign")
    question = await create(
        api, "question", title="How to reuse knowledge?", project_id=project["id"]
    )
    standalone = await create(api, "question", title="Validate portability?")
    for ctx in (question, standalone, project):
        await create(
            api, "usage", context_id=ctx["id"], knowledge_id=entity["id"], knowledge_revision=1
        )
    await api.patch(
        f"knowledge/records/{entity['id']}",
        json={"expected_revision": 1, "data": {**entity["data"], "summary": "Second revision"}},
    )
    archived = await api.patch(
        f"knowledge/records/{question['id']}",
        headers={"X-EchoMe-Review-Key": "test-reviewer-capability"},
        json={"expected_revision": 1, "data": {**question["data"], "status": "archived"}},
    )
    assert archived.status_code == 200, archived.text
    endpoint = f"knowledge/records/{entity['id']}/connections"
    domains = (await api.get(endpoint, params={"section": "domains", "limit": 1})).json()
    assert domains["total"] == 2 and domains["next_offset"] == 1
    assert [item["id"] for item in domains["items"][0]["nodes"]] == [
        root["id"],
        sub["id"],
        entity["id"],
    ]
    assert not domains["items"][0]["incomplete"]
    following = (
        await api.get(endpoint, params={"section": "domains", "limit": 1, "offset": 1})
    ).json()
    assert following["next_offset"] is None and [
        n["id"] for n in following["items"][0]["nodes"]
    ] == [root["id"], entity["id"]]
    uses = (await api.get(endpoint, params={"section": "uses", "limit": 1})).json()
    assert uses["total"] == 3 and uses["next_offset"] == 1
    use = uses["items"][0]
    assert use["project"]["id"] == project["id"] and use["context"]["id"] == question["id"]
    assert use["context"]["status"] == "archived"
    assert use["knowledge_revision"] == 1 and use["current_revision"] == 2
    rest = (await api.get(endpoint, params={"section": "uses", "offset": 1})).json()
    assert (
        rest["items"][0]["project"] is None
        and rest["items"][0]["context"]["id"] == standalone["id"]
    )
    assert rest["items"][1]["project"] is None and rest["items"][1]["context"]["kind"] == "project"
    headers = await other_headers(database)
    assert (await api.get(endpoint, headers=headers)).status_code == 404
    # An inactive ancestor is shown as an incomplete path, never as an invented new root.
    await api.patch(
        f"knowledge/records/{root_position['id']}",
        json={"expected_revision": 1, "data": {**root_position["data"], "status": "archived"}},
    )
    changed = (await api.get(endpoint)).json()["items"]
    assert all(path["incomplete"] for path in changed)


async def test_global_search_body_aliases_category_counts_ranking_and_private_data(api, database):
    project = await create(api, "project", name="Trace project")
    question = await create(api, "question", title="Trace question", project_id=project["id"])
    domain = await create(api, "entity", name="Trace domain", entity_kind="topic")
    position = await create(api, "placement", entity_id=domain["id"])
    entity = await create(api, "entity", name="Trace", entity_kind="method", aliases=["复用方法"])
    await create(api, "placement", entity_id=entity["id"], parent_id=position["id"])
    overview = await create(
        api,
        "page",
        title="Method overview",
        body_md="Trace details and 正文唯一词",
        bindings=[{"target_id": entity["id"], "role": "overview"}],
    )
    document = await create(api, "page", title="Trace notes", body_md="Supplementary text")
    source = await create(
        api, "source", title="Trace source", source_kind="practice", origin_ref="local execution"
    )
    output = await create(
        api,
        "deliverable",
        title="Trace output",
        project_id=project["id"],
        question_id=question["id"],
        resource_ref="https://example.org/trace.txt",
        format="txt",
    )
    expected = {r["id"] for r in (project, question, domain, entity, document, source, output)}
    first = (await api.get("knowledge/search", params={"q": "Trace", "limit": 2})).json()
    assert first["total"] == 7 and first["next_offset"] == 2
    assert first["counts"] == {
        key: 1
        for key in (
            "projects",
            "questions",
            "domains",
            "knowledge",
            "pages",
            "sources",
            "deliverables",
        )
    }
    assert first["items"][0]["id"] == entity["id"]
    assert [n["id"] for n in first["items"][0]["locations"][0]["nodes"]] == [domain["id"]]
    found = {row["id"] for row in first["items"]}
    offset = first["next_offset"]
    while offset is not None:
        result = (
            await api.get("knowledge/search", params={"q": "Trace", "limit": 2, "offset": offset})
        ).json()
        found.update(row["id"] for row in result["items"])
        offset = result["next_offset"]
    assert found == expected and overview["id"] not in found
    for query in ("正文唯一词", "复用方法"):
        result = (await api.get("knowledge/search", params={"q": query})).json()
        assert result["total"] == 1 and result["items"][0]["id"] == entity["id"]
    selected = (
        await api.get("knowledge/search", params={"q": "Trace", "category": "questions"})
    ).json()
    assert selected["total"] == 1 and selected["counts"] == first["counts"]
    assert selected["items"][0]["locations"][0]["nodes"][0]["id"] == project["id"]
    literal = await create(api, "entity", name="50% complete")
    result = (await api.get("knowledge/search", params={"q": "%"})).json()
    assert result["total"] == 1 and result["items"][0]["id"] == literal["id"]
    await api.patch(
        f"knowledge/records/{source['id']}",
        json={"expected_revision": 1, "data": {**source["data"], "status": "archived"}},
    )
    assert (await api.get("knowledge/search", params={"q": "Trace"})).json()["total"] == 6
    headers = await other_headers(database)
    for query in ("Trace", "正文唯一词", "复用方法"):
        private = (await api.get("knowledge/search", params={"q": query}, headers=headers)).json()
        assert private["total"] == 0 and private["counts"] == {} and private["items"] == []
    assert (
        await api.get("knowledge/search", params={"q": "Trace", "category": "invalid"})
    ).status_code == 422
