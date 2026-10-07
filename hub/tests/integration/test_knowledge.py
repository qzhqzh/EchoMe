"""Real PostgreSQL acceptance of ownership, history, graph and review boundaries."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.jwt import create_access_token
from app.models import User
from app.models.knowledge import KnowledgeRecord

pytestmark = pytest.mark.asyncio


async def create(api, kind, **data):
    response = await api.post("knowledge/records", json={"kind": kind, "data": data})
    assert response.status_code == 201, response.text
    return response.json()


async def test_project_independent_knowledge_and_pinned_pages(api):
    project = await create(api, "project", name="Whale workflow")
    q1 = await create(api, "question", title="Build Blender model?", project_id=project["id"])
    q2 = await create(api, "question", title="Can we reuse the geometry method?")
    entity = await create(api, "entity", name="Procedural modeling", entity_kind="method")
    page = await create(
        api,
        "page",
        title="Method",
        body_md="Requires shape checks.",
        bindings=[{"target_id": entity["id"], "role": "overview"}],
    )
    uses = []
    for q in (q1, q2):
        uses.append(
            await create(
                api,
                "usage",
                context_id=q["id"],
                knowledge_id=entity["id"],
                knowledge_revision=1,
                page_id=page["id"],
                page_revision=1,
                application_note=q["data"]["title"],
            )
        )
    updated = await api.patch(
        f"knowledge/records/{page['id']}",
        json={
            "expected_revision": 1,
            "data": {**page["data"], "body_md": "Also compare side views."},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    old = (await api.get(f"knowledge/records/{page['id']}?revision=1")).json()
    assert old["data"]["body_md"] == "Requires shape checks."
    context = (await api.get(f"knowledge/records/{project['id']}/context")).json()
    assert any(r["id"] == entity["id"] for r in context["records"])
    assert any(r["id"] == page["id"] and r["revision"] == 1 for r in context["pinned_versions"])
    await api.patch(
        f"knowledge/records/{project['id']}",
        json={"expected_revision": 1, "data": {**project["data"], "status": "archived"}},
    )
    assert (await api.get(f"knowledge/records/{entity['id']}")).json()["status"] == "active"
    assert all(u["data"]["knowledge_id"] == entity["id"] for u in uses)
    assert "project_id" not in entity["data"]


async def test_ownership_type_and_overview_constraints(api, database):
    other = uuid4()
    async with database() as session:
        session.add(User(id=other, github_id=987, username="other"))
        await session.commit()
    entity = await create(api, "entity", name="Private method")
    headers = {"Authorization": "Bearer " + create_access_token(other, "other", "user")[0]}
    assert (await api.get(f"knowledge/records/{entity['id']}", headers=headers)).status_code == 404
    assert (
        await api.post(
            "knowledge/records",
            headers=headers,
            json={"kind": "placement", "data": {"entity_id": entity["id"]}},
        )
    ).status_code == 404
    assert (
        await api.post(
            "knowledge/records",
            json={
                "kind": "question",
                "data": {"title": "Bad project reference", "project_id": entity["id"]},
            },
        )
    ).status_code == 422
    await create(
        api, "page", title="Overview", bindings=[{"target_id": entity["id"], "role": "overview"}]
    )
    assert (
        await api.post(
            "knowledge/records",
            json={
                "kind": "page",
                "data": {
                    "title": "Second overview",
                    "bindings": [{"target_id": entity["id"], "role": "overview"}],
                },
            },
        )
    ).status_code == 409


async def test_atomic_version_conflict_and_directory_cycle(api):
    entity = await create(api, "entity", name="A")
    responses = await asyncio.gather(
        *[
            api.patch(
                f"knowledge/records/{entity['id']}",
                json={"expected_revision": 1, "data": {**entity["data"], "summary": value}},
            )
            for value in ("first", "second")
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    p1 = await create(api, "placement", entity_id=entity["id"])
    e2 = await create(api, "entity", name="B")
    p2 = await create(api, "placement", entity_id=e2["id"], parent_id=p1["id"])
    response = await api.patch(
        f"knowledge/records/{p1['id']}",
        json={"expected_revision": 1, "data": {**p1["data"], "parent_id": p2["id"]}},
    )
    assert response.status_code == 422


async def test_knowledge_catalog_excludes_topics_before_search_and_pagination(api):
    topic = await create(api, "entity", name="Shared catalog", entity_kind="topic")
    method = await create(api, "entity", name="Shared method", entity_kind="method")
    concept = await create(api, "entity", name="Camera framing", entity_kind="concept")
    await create(
        api,
        "page",
        title="Framing guide",
        body_md="Shared guidance from a practical example.",
        bindings=[{"target_id": concept["id"], "role": "overview"}],
    )

    for mode in ("list", "query", "search"):

        async def fetch(request_mode=mode, **extra):
            params = {"kind": "entity", "exclude_entity_kind": "topic", "limit": 1, **extra}
            if request_mode == "query":
                return await api.post("knowledge/query", json=params)
            if request_mode == "search":
                params["search"] = "Shared"
            return await api.get("knowledge/records", params=params)

        response = await fetch()
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["total"] == 2 and first["next_offset"] == 1
        assert first["exclude_entity_kind"] == "topic"
        second = (await fetch(offset=first["next_offset"])).json()
        assert second["total"] == 2 and second["next_offset"] is None
        assert {r["id"] for r in first["items"] + second["items"]} == {method["id"], concept["id"]}

    default = (await api.get("knowledge/records", params={"kind": "entity"})).json()
    assert default["total"] == 3 and any(r["id"] == topic["id"] for r in default["items"])
    selected = (
        await api.get(
            "knowledge/records",
            params={"kind": "entity", "exclude_entity_kind": "topic", "entity_kind": "concept"},
        )
    ).json()
    assert selected["total"] == 1 and selected["items"][0]["id"] == concept["id"]
    empty = (
        await api.get(
            "knowledge/records",
            params={"kind": "entity", "exclude_entity_kind": "topic", "search": "Shared catalog"},
        )
    ).json()
    assert empty["total"] == 0 and empty["items"] == []
    assert (
        await api.get(
            "knowledge/records", params={"kind": "entity", "exclude_entity_kind": "unknown"}
        )
    ).status_code == 422
    assert (
        await api.post("knowledge/query", json={"kind": "project", "exclude_entity_kind": "topic"})
    ).status_code == 422


async def test_directory_preserves_hierarchy_placements_and_pagination(api):
    root = await create(api, "entity", name="Digital creation", entity_kind="topic")
    root_position = await create(api, "placement", entity_id=root["id"])
    child = await create(api, "entity", name="3D modeling", entity_kind="topic")
    child_position = await create(
        api, "placement", entity_id=child["id"], parent_id=root_position["id"], sort_order=2
    )
    method = await create(api, "entity", name="Model validation", entity_kind="method")
    leaf = await create(api, "placement", entity_id=method["id"], parent_id=child_position["id"])
    second_position = await create(
        api, "placement", entity_id=method["id"], parent_id=root_position["id"], sort_order=1
    )
    await create(api, "entity", name="Unplaced method", entity_kind="method")
    unplaced = await create(api, "entity", name="Networking", entity_kind="topic")

    result = (await api.get("knowledge/directory")).json()
    assert result["total"] == 1 and result["next_offset"] is None
    assert result["unplaced_total"] == 1
    assert result["items"][0]["entity_id"] == root["id"]
    assert result["items"][0]["placement_id"] == root_position["id"]
    assert result["items"][0]["child_count"] == 2

    params = {"parent_id": root_position["id"], "limit": 1}
    branch = (await api.get("knowledge/directory", params=params)).json()
    assert branch["total"] == 2 and branch["next_offset"] == 1
    assert branch["items"][0]["placement_id"] == second_position["id"]
    page_two = (await api.get("knowledge/directory", params={**params, "offset": 1})).json()
    assert page_two["next_offset"] is None
    assert page_two["items"][0]["placement_id"] == child_position["id"]
    assert page_two["items"][0]["child_count"] == 1
    nested = (
        await api.get("knowledge/directory", params={"parent_id": child_position["id"]})
    ).json()
    assert nested["items"][0]["placement_id"] == leaf["id"]
    assert nested["items"][0]["entity_id"] == second_position["data"]["entity_id"]
    assert nested["items"][0]["child_count"] == 0
    empty = (await api.get("knowledge/directory", params={"parent_id": leaf["id"]})).json()
    assert empty["items"] == [] and empty["total"] == 0
    uncategorized = (await api.get("knowledge/directory", params={"unplaced": True})).json()
    assert uncategorized["total"] == 1
    assert uncategorized["items"][0]["entity_id"] == unplaced["id"]
    assert uncategorized["items"][0]["placement_id"] is None
    for params in (
        {"parent_id": root["id"]},
        {"parent_id": str(uuid4())},
    ):
        assert (await api.get("knowledge/directory", params=params)).status_code == 404
    assert (
        await api.get(
            "knowledge/directory", params={"parent_id": root_position["id"], "search": "3D"}
        )
    ).status_code == 422


async def test_directory_search_paths_visibility_and_ownership(api, database, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    root = await create(api, "entity", name="Digital creation", entity_kind="topic")
    root_position = await create(api, "placement", entity_id=root["id"])
    child = await create(api, "entity", name="3D modeling", entity_kind="topic", aliases=["CG"])
    child_position = await create(
        api, "placement", entity_id=child["id"], parent_id=root_position["id"]
    )
    await create(api, "placement", entity_id=child["id"])
    await create(
        api,
        "page",
        title="CG overview",
        body_md="Silhouette practice",
        bindings=[{"target_id": child["id"], "role": "overview"}],
    )
    for search in ("CG", "Silhouette"):
        result = (await api.get("knowledge/directory", params={"search": search})).json()
        assert result["total"] == 1
        match = result["items"][0]
        assert match["entity_id"] == child["id"]
        assert {tuple(path["names"]) for path in match["paths"]} == {
            ("Digital creation", "3D modeling"),
            ("3D modeling",),
        }
        assert all(not path["incomplete"] for path in match["paths"])

    other = uuid4()
    async with database() as session:
        session.add(User(id=other, github_id=998, username="directory-other"))
        await session.commit()
    headers = {
        "Authorization": "Bearer " + create_access_token(other, "directory-other", "user")[0]
    }
    for params in ({}, {"search": "CG"}, {"unplaced": True}):
        response = await api.get("knowledge/directory", params=params, headers=headers)
        assert response.status_code == 200
        assert response.json()["items"] == [] and response.json()["total"] == 0
    assert (
        await api.get(
            "knowledge/directory", params={"parent_id": root_position["id"]}, headers=headers
        )
    ).status_code == 404

    # Archived ancestors must neither leak through search paths nor promote children to roots.
    response = await api.patch(
        f"knowledge/records/{root['id']}",
        headers={"X-EchoMe-Review-Key": "test-reviewer-capability"},
        json={"expected_revision": 1, "data": {**root["data"], "status": "archived"}},
    )
    assert response.status_code == 200, response.text
    roots = (await api.get("knowledge/directory")).json()
    assert roots["total"] == 1
    assert all(row["placement_id"] != child_position["id"] for row in roots["items"])
    assert (
        await api.get("knowledge/directory", params={"parent_id": root_position["id"]})
    ).status_code == 404
    found = (await api.get("knowledge/directory", params={"search": "CG"})).json()["items"][0]
    assert all(path["names"] == ["3D modeling"] for path in found["paths"])
    assert {path["incomplete"] for path in found["paths"]} == {False, True}
    response = await api.patch(
        f"knowledge/records/{child_position['id']}",
        json={"expected_revision": 1, "data": {**child_position["data"], "status": "archived"}},
    )
    assert response.status_code == 200, response.text
    found = (await api.get("knowledge/directory", params={"search": "CG"})).json()["items"][0]
    assert found["paths"] == [{"names": ["3D modeling"], "incomplete": False}]


async def test_evidence_and_exact_query_pagination(api):
    entity = await create(api, "entity", name="Blender")
    predicate = await create(
        api, "predicate", code="requires", label="Requires", value_kind="scalar"
    )
    source = await create(
        api,
        "source",
        title="Observed practice",
        source_kind="practice",
        retention="excerpt",
        content_text="Validate the silhouette from multiple views.",
    )
    for value in ("front", "side", "back"):
        await create(
            api,
            "relation",
            subject_id=entity["id"],
            predicate_id=predicate["id"],
            object_value={"type": "string", "value": value},
            perspective="personal",
            evidence=[
                {
                    "source_id": source["id"],
                    "source_revision": 1,
                    "locator": "practice",
                    "quote": "Validate the silhouette",
                    "role": "supports",
                }
            ],
        )
    query = {"kind": "relation", "filters": {"subject_id": entity["id"]}, "limit": 2}
    first = (await api.post("knowledge/query", json=query)).json()
    assert first["total"] == 3 and first["complete"] is False and first["next_offset"] == 2
    assert first["items"][0]["evidence_checks"][0]["verification_state"] == "matched"
    second = (await api.post("knowledge/query", json={**query, "offset": 2})).json()
    assert second["complete"] is True and len(second["items"]) == 1
    assert (
        await api.post("knowledge/query", json={"kind": "relation", "filters": {"fake": 1}})
    ).status_code == 422
    assert (
        await api.post(
            "knowledge/records",
            json={
                "kind": "relation",
                "data": {"subject_id": entity["id"], "predicate_id": predicate["id"]},
            },
        )
    ).status_code == 422


async def test_review_dedup_stale_proposals_and_scoped_ai(api, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    a = await create(api, "entity", name="Same name")
    b = await create(api, "entity", name="Same name")
    issues = (await api.get("knowledge/records?kind=review")).json()["items"]
    assert len(issues) == 1
    issue = issues[0]
    repeat = await create(api, "review", **issue["data"])
    assert repeat["id"] == issue["id"]
    token = (await api.post("knowledge/agent-tokens", json={"name": "Blender agent"})).json()
    ai_headers = {
        "Authorization": "Bearer " + token["token"],
        "X-EchoMe-Review-Key": "test-reviewer-capability",
    }
    body = {"expected_revision": 1, "action": "apply", "note": "same meaning"}
    assert (
        await api.post(f"knowledge/reviews/{issue['id']}/decisions", json=body, headers=ai_headers)
    ).status_code == 403
    assert (
        await api.post(f"knowledge/reviews/{issue['id']}/decisions", json=body)
    ).status_code == 403
    await api.patch(
        f"knowledge/records/{a['id']}",
        json={"expected_revision": 1, "data": {**a["data"], "summary": "different meaning"}},
    )
    headers = {"X-EchoMe-Review-Key": "test-reviewer-capability"}
    assert (
        await api.post(f"knowledge/reviews/{issue['id']}/decisions", json=body, headers=headers)
    ).status_code == 409
    assert (await api.get(f"knowledge/records/{b['id']}")).json()["status"] == "active"
    await api.delete(f"knowledge/agent-tokens/{token['id']}")
    assert (await api.get("knowledge/schema", headers=ai_headers)).status_code == 401


async def test_verified_revision_requires_review_and_deprecation_visible(api, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    headers = {"X-EchoMe-Review-Key": "test-reviewer-capability"}
    entity = await create(api, "entity", name="Versioned method")
    question = await create(api, "question", title="Apply it")
    usage = await create(
        api, "usage", context_id=question["id"], knowledge_id=entity["id"], knowledge_revision=1
    )
    verify = await create(
        api,
        "review",
        title="Verify",
        issue_kind="verification",
        explanation="Evidence checked",
        targets=[{"id": entity["id"], "revision": 1}],
        proposal={"operation": "verify", "target_id": entity["id"]},
    )
    result = await api.post(
        f"knowledge/reviews/{verify['id']}/decisions",
        headers=headers,
        json={"expected_revision": 1, "action": "apply"},
    )
    assert result.status_code == 200, result.text
    assert (await api.get(f"knowledge/records/{entity['id']}")).json()["review_state"] == "reviewed"
    assert (
        await api.patch(
            f"knowledge/records/{entity['id']}",
            json={"expected_revision": 1, "data": {**entity["data"], "summary": "silent rewrite"}},
        )
    ).status_code == 403
    issue = await create(
        api,
        "review",
        title="Wrong method",
        issue_kind="conflict",
        explanation="Counterevidence",
        targets=[{"id": entity["id"], "revision": 1}],
        proposal={"operation": "archive", "target_id": entity["id"]},
    )
    assert (
        await api.post(
            f"knowledge/reviews/{issue['id']}/decisions",
            headers=headers,
            json={"expected_revision": 1, "action": "apply"},
        )
    ).status_code == 200
    read_usage = (await api.get(f"knowledge/records/{usage['id']}")).json()
    assert read_usage["knowledge_current_status"] == "archived" and read_usage["warnings"]
    assert (await api.get("knowledge/records?kind=entity")).json()["total"] == 0
    assert (await api.get(f"knowledge/records/{entity['id']}?revision=1")).json()["data"][
        "status"
    ] == "active"


async def test_deliverables_assets_and_acceptance_versions(api, monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.settings.knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    project = await create(api, "project", name="Actual outputs")
    criteria = await create(
        api, "page", title="Criteria", body_md="File opens, shape matches reference."
    )
    uploaded = await api.post(
        "knowledge/assets?filename=steps.txt",
        content=b"actual steps",
        headers={"Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 201
    assert (await api.get("knowledge/assets/" + uploaded.json()["id"])).content == b"actual steps"
    output = await create(
        api,
        "deliverable",
        title="Reproduction steps",
        project_id=project["id"],
        resource_ref=uploaded.json()["resource_ref"],
    )
    data = {
        "deliverable_id": output["id"],
        "deliverable_revision": 1,
        "criteria_page_id": criteria["id"],
        "criteria_page_revision": 1,
        "state": "accepted",
        "checks": "Opens and matches",
    }
    assert (
        await api.post("knowledge/records", json={"kind": "acceptance", "data": data})
    ).status_code == 403
    accepted = await api.post(
        "knowledge/records",
        json={"kind": "acceptance", "data": data},
        headers={"X-EchoMe-Review-Key": "test-reviewer-capability"},
    )
    assert accepted.status_code == 201
    updated = await api.patch(
        f"knowledge/records/{output['id']}",
        json={"expected_revision": 1, "data": {**output["data"], "title": "Updated output"}},
    )
    assert updated.status_code == 200
    assert accepted.json()["data"]["deliverable_revision"] == 1


async def test_review_cannot_be_bypassed_by_a_new_dispute(api, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    reviewer = {"X-EchoMe-Review-Key": "test-reviewer-capability"}
    entity = await create(api, "entity", name="Protected revision")
    issue = await create(
        api,
        "review",
        title="Check it",
        issue_kind="verification",
        explanation="Checked scope",
        targets=[{"id": entity["id"], "revision": 1}],
        proposal={"operation": "verify", "target_id": entity["id"]},
    )
    assert (
        await api.post(
            f"knowledge/reviews/{issue['id']}/decisions",
            json={"action": "apply", "expected_revision": 1},
            headers=reviewer,
        )
    ).status_code == 200
    await create(
        api,
        "review",
        title="New doubt",
        issue_kind="conflict",
        explanation="Needs more evidence",
        targets=[{"id": entity["id"], "revision": 1}],
    )
    assert (await api.get(f"knowledge/records/{entity['id']}")).json()["review_state"] == "disputed"
    assert (
        await api.patch(
            f"knowledge/records/{entity['id']}",
            json={
                "expected_revision": 1,
                "data": {**entity["data"], "summary": "Unapproved rewrite"},
            },
        )
    ).status_code == 403


async def test_merge_query_resolves_old_ids_and_deprecation_excludes_relations(api, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.knowledge_review_key", "test-reviewer-capability")
    reviewer = {"X-EchoMe-Review-Key": "test-reviewer-capability"}
    old = await create(api, "entity", name="Old label")
    canonical = await create(api, "entity", name="Canonical label")
    predicate = await create(
        api, "predicate", code="has_note", label="Has note", value_kind="scalar"
    )
    relation = await create(
        api,
        "relation",
        subject_id=old["id"],
        predicate_id=predicate["id"],
        object_value={"type": "string", "value": "fact"},
    )
    issue = await create(
        api,
        "review",
        title="Same meaning",
        issue_kind="duplicate",
        explanation="Same subject",
        targets=[{"id": old["id"], "revision": 1}, {"id": canonical["id"], "revision": 1}],
        proposal={"operation": "merge", "target_id": old["id"], "into_id": canonical["id"]},
    )
    assert (
        await api.post(
            f"knowledge/reviews/{issue['id']}/decisions",
            json={"action": "apply", "expected_revision": 1},
            headers=reviewer,
        )
    ).status_code == 200
    query = {"kind": "relation", "filters": {"subject_id": canonical["id"]}}
    result = (await api.post("knowledge/query", json=query)).json()
    assert [r["id"] for r in result["items"]] == [relation["id"]]
    assert result["items"][0]["data"]["subject_id"] == old["id"]
    archived_data = {"expected_revision": 1, "data": {**canonical["data"], "status": "archived"}}
    assert (
        await api.patch(f"knowledge/records/{canonical['id']}", json=archived_data)
    ).status_code == 403
    assert (
        await api.patch(
            f"knowledge/records/{canonical['id']}", json=archived_data, headers=reviewer
        )
    ).status_code == 200
    assert (await api.post("knowledge/query", json=query)).json()["total"] == 0
    assert (await api.get(f"knowledge/records/{relation['id']}")).json()["reusable"] is False
    assert (
        await api.patch(
            f"knowledge/records/{old['id']}",
            json={"expected_revision": 2, "data": {**old["data"], "status": "active"}},
        )
    ).status_code == 403


async def test_context_has_explicit_budget_and_project_metadata_stays_consistent(api):
    project = await create(api, "project", name="Original name")
    page = await create(
        api,
        "page",
        title="Full document",
        body_md="x" * 15000,
        bindings=[{"target_id": project["id"], "role": "overview"}],
    )
    bundle = (await api.get(f"knowledge/records/{project['id']}/context?max_chars=8000")).json()
    assert bundle["truncated"] and bundle["omitted_fields"]
    assert (
        len((await api.get(f"knowledge/records/{page['id']}")).json()["data"]["body_md"]) == 15000
    )
    renamed = await api.put(
        "projects/" + project["project_id"],
        json={
            "id": project["project_id"],
            "name": "Changed from Projects API",
            "description": "Updated summary",
        },
    )
    assert renamed.status_code == 200, renamed.text
    knowledge_project = (await api.get(f"knowledge/records/{project['id']}")).json()
    assert knowledge_project["revision"] == 2
    assert knowledge_project["data"]["name"] == "Changed from Projects API"
    assert (await api.delete("projects/" + project["project_id"])).status_code == 409
    found = (
        await api.get("knowledge/records", params={"kind": "project", "search": "xxxxx"})
    ).json()
    assert [item["id"] for item in found["items"]] == [project["id"]]
