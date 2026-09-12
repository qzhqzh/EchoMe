"""Exercise real HTTP/auth/SQL boundaries and embedding completion races."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.api.memories import _compute_and_store_embedding
from app.models import ContextOutcome, ContextRun, Memory, Project, ProjectAlias
from app.services.project_identity import discover_projects, normalize_project_hint


async def seed_projects(database, user_id):
    async with database() as session:
        session.add_all(
            [
                Project(id="OKB", name="OKB", user_id=user_id),
                Project(id="other", name="Other", user_id=user_id),
                Project(id="foreign", name="Foreign", user_id="another-user"),
            ]
        )
        await session.flush()
        for kind, value in [
            ("legacy_id", "legacy-okb"),
            ("path", "/workspace/okb/api"),
            ("path", "/workspace/okb/web"),
            ("git_remote", "https://example.test/okb/api.git"),
            ("git_remote", "https://example.test/okb/web.git"),
        ]:
            session.add(
                ProjectAlias(
                    user_id=user_id,
                    canonical_project_id="OKB",
                    alias_type=kind,
                    alias_value=value,
                    normalized_value=normalize_project_hint(value, kind),
                    status="active",
                    source="user",
                    confidence=1.0,
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_aliases_exclusions_and_user_isolation(api, database, test_user_id):
    await seed_projects(database, test_user_id)
    async with database() as session:
        for title, scopes, excluded, global_, owner in [
            ("scope visible", ["OKB"], [], False, test_user_id),
            ("scope excluded canonical", ["OKB"], ["OKB"], False, test_user_id),
            ("scope excluded legacy", [], ["legacy-okb"], True, test_user_id),
            ("scope foreign secret", ["OKB"], [], False, "another-user"),
        ]:
            session.add(
                Memory(
                    user_id=owner,
                    title=title,
                    content=title,
                    type="guardrail",
                    layer="L0" if global_ else "L1",
                    scope_global=global_,
                    scope_projects=scopes,
                    scope_exclude=excluded,
                )
            )
        await session.commit()
    for hint in [
        "OKB",
        "legacy-okb",
        "/workspace/okb/api",
        "/workspace/okb/web",
        "https://example.test/okb/api.git",
        "https://example.test/okb/web.git",
    ]:
        responses = [
            await api.post("memories/search", json={"query": "scope", "project_id": hint}),
            await api.get("memories", params={"project_id": hint}),
            await api.post("sync/render", json={"target": "codex", "project_id": hint}),
            await api.post(
                "context",
                json={
                    "task": "scope",
                    "project_hint": hint,
                    "record_run": False,
                },
            ),
        ]
        for response in responses:
            assert response.status_code == 200, response.text
            assert "scope visible" in response.text
            assert "scope excluded" not in response.text
            assert "scope foreign secret" not in response.text
    allowed = await api.post("memories/search", json={"query": "scope", "project_id": "other"})
    assert "scope excluded legacy" in allowed.text
    global_render = await api.post("sync/render", json={"target": "codex"})
    assert "scope excluded legacy" not in global_render.text
    # Explicit conflicting identities require confirmation; no project is created.
    async with database() as session:
        ambiguous = await discover_projects(session, test_user_id, ["OKB", "other"])
        assert ambiguous.resolution is None
        foreign = await discover_projects(session, test_user_id, ["foreign"])
        assert foreign.resolution is None
        assert await session.scalar(select(func.count()).select_from(Project)) == 3


@pytest.mark.asyncio
async def test_memory_context_feedback_archive_lifecycle(api, database):
    created = await api.post(
        "memories",
        json={
            "title": "release convention",
            "content": "Check the release smoke before shipping.",
            "type": "method",
            "layer": "L0",
            "status": "ai_review",
        },
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    context = await api.post("context", json={"task": "release", "mode": "personal"})
    assert context.status_code == 200, context.text
    payload = context.json()
    assert memory_id in [item["id"] for item in payload["memories"]]
    feedback = await api.post("memory-feedback", json={"memory_id": memory_id, "rating": "helpful"})
    assert feedback.status_code == 201, feedback.text
    outcome = {
        "context_run_id": payload["context_run_id"],
        "outcome": "success",
        "idempotency_key": payload["completion_contract"]["idempotency_key"],
    }
    first = await api.post("context-outcomes", json=outcome)
    again = await api.post("context-outcomes", json=outcome)
    assert first.status_code == again.status_code == 201, first.text
    assert first.json()["id"] == again.json()["id"]
    conflict = await api.post("context-outcomes", json={**outcome, "outcome": "partial"})
    assert conflict.status_code == 409
    archived = await api.patch(f"memories/{memory_id}", json={"status": "archived"})
    assert archived.status_code == 200, archived.text
    after = await api.post("context", json={"task": "release", "mode": "personal"})
    assert after.json()["memories"] == []
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(ContextOutcome)) == 1
        assert await session.scalar(select(func.count()).select_from(ContextRun)) == 2
        assert (await session.get(Memory, uuid.UUID(memory_id))).status == "archived"
    unauthorized = await api.get(
        f"memories/{memory_id}", headers={"Authorization": "Bearer invalid"}
    )
    assert unauthorized.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["personal", "project", "impact", "temporal"])
@pytest.mark.parametrize("policy_mode", ["off", "shadow", "enforce"])
async def test_complete_output_budget_and_diagnostics(
    api,
    database,
    test_user_id,
    mode,
    policy_mode,
):
    from app.services.context_output import measure_output

    await seed_projects(database, test_user_id)
    body = {
        "task": "release",
        "mode": mode,
        "policy_mode": policy_mode,
        "output_mode": "compact",
        "max_output_tokens": 6000,
    }
    if mode != "personal":
        body["project_hint"] = "OKB"
    if mode == "impact":
        body["changed_paths"] = ["api/main.py"]
    response = await api.post("context", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["output_mode"] == "compact", result
    assert result["unknowns"]  # A fresh fixture must not claim unsupported facts.
    assert result["output_usage"]["tokens_upper_bound"] == measure_output(result) <= 6000
    diagnostics_url = "http://integration" + result["diagnostics"]["href"]
    diagnostics = await api.get(diagnostics_url)
    assert diagnostics.status_code == 200, diagnostics.text
    assert diagnostics.json()["trace"]["output_usage"] == result["output_usage"]
    denied = await api.get(diagnostics_url, headers={"Authorization": "Bearer invalid"})
    assert denied.status_code == 401
    tiny = await api.post("context", json={**body, "max_output_tokens": 256})
    assert tiny.json()["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    assert len(tiny.content) <= 256


@pytest.mark.asyncio
async def test_compact_audit_records_delivered_ids_and_sync_invalidates_embedding(
    api, database, test_user_id,
):
    async with database() as session:
        memory = Memory(
            user_id=test_user_id, title="release background", content="Release detail. " * 3000,
            type="context", layer="L2", embedding=[0.3] * 1024,
        )
        session.add(memory)
        await session.commit()
        memory_id = str(memory.id)
    response = await api.post("context", json={
        "task": "release", "mode": "personal", "output_mode": "compact",
        "token_budget": 50000, "max_output_tokens": 5000,
    })
    context = response.json()
    assert context["memories"] == [], response.text
    assert context["answerability"] == "insufficient_evidence"
    async with database() as session:
        run = await session.get(ContextRun, uuid.UUID(context["context_run_id"]))
        assert run.selected["memories"] == []
        assert run.trace["compiled_selected"]["memories"] == [memory_id]
    pushed = await api.post("sync/push", json={"memories": [{
        "id": memory_id, "title": "release background", "content": "Updated release fact.",
        "type": "context", "layer": "L2", "priority": 5, "tags": [], "status": "active",
        "scope": {"global": True, "projects": [], "exclude_projects": []}, "source": "manual",
    }]})
    assert pushed.status_code == 200, pushed.text
    async with database() as session:
        row = await session.get(Memory, uuid.UUID(memory_id))
        assert row.content == "Updated release fact."
        assert row.embedding is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["new_content", "metadata", "archived", "deprecated", "deleted", "superseded"]
)
async def test_embedding_completion_cannot_overwrite_newer_state(
    database,
    monkeypatch,
    test_user_id,
    change,
):
    memory_id = uuid.uuid4()
    async with database() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=test_user_id,
                title="A",
                content="original",
                type="context",
                layer="L2",
            )
        )
        await session.commit()
    started, release = asyncio.Event(), asyncio.Event()

    async def embedding(text):
        if text == "A\noriginal":
            started.set()
            await release.wait()
            return [0.1] * 1024
        return [0.2] * 1024

    monkeypatch.setattr("app.api.memories.get_embedding", embedding)
    old_task = asyncio.create_task(_compute_and_store_embedding(memory_id, "A\noriginal"))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        async with database() as session:
            row = await session.get(Memory, memory_id)
            if change == "deleted":
                await session.delete(row)
            elif change == "new_content":
                row.content = "new content"
            elif change == "metadata":
                row.layer, row.tags = "L1", ["edited"]
            elif change == "superseded":
                replacement = Memory(
                    user_id=test_user_id,
                    title="B",
                    content="replacement",
                    type="context",
                    layer="L2",
                )
                session.add(replacement)
                await session.flush()
                row.superseded_by = replacement.id
            else:
                row.status = change
            await session.commit()
            changed_at = row.updated_at
        if change == "new_content":
            await _compute_and_store_embedding(memory_id, "A\nnew content")
    finally:
        release.set()
        await asyncio.wait_for(old_task, timeout=5)
    async with database() as session:
        row = await session.get(Memory, memory_id)
        if change == "deleted":
            assert row is None
        else:
            assert row.updated_at == changed_at
            if change == "new_content":
                assert list(row.embedding) == pytest.approx([0.2] * 1024)
            elif change == "metadata":
                assert list(row.embedding) == pytest.approx([0.1] * 1024)
                assert row.layer == "L1" and row.tags == ["edited"]
            else:
                assert row.embedding is None
