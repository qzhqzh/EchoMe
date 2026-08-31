"""Composite workspace identity, relation, and memory-scope tests."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.projects import (
    ProjectCreate,
    ProjectRelationCreate,
    ProjectRelationPatch,
    _validate_relation_projects,
    create_project_relation,
    update_project_relation,
)
from app.models.memory import Memory, Project
from app.models.project_knowledge import ProjectAlias, ProjectRelation
from app.services.context_compiler import _memory_scope_tier
from app.services.project_identity import (
    ProjectContextScope,
    ProjectResolution,
    project_context_scope,
    project_matches_changed_paths,
)


def _result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _project(project_id: str, kind: str) -> Project:
    return Project(
        id=project_id,
        user_id="user",
        name=project_id,
        kind=kind,
        path_patterns=[],
    )


def _alias(project_id: str, alias_type: str, value: str) -> ProjectAlias:
    return ProjectAlias(
        user_id="user",
        canonical_project_id=project_id,
        alias_type=alias_type,
        alias_value=value,
        normalized_value=value.casefold(),
        status="active",
        source="manual",
        confidence=1,
    )


def test_project_create_defaults_to_repository_for_existing_clients() -> None:
    assert ProjectCreate(id="repo", name="Repository").kind == "repository"


def test_changed_paths_match_absolute_alias_and_workspace_relative_path() -> None:
    project = _project("tumor_api", "repository")

    assert project_matches_changed_paths(
        project,
        ["/home/zhuqin/project/zhenyuan/tumor_api"],
        ["/home/zhuqin/project/zhenyuan/tumor_api/app/main.py"],
    )
    assert project_matches_changed_paths(
        project,
        ["/home/zhuqin/project/zhenyuan/tumor_api"],
        ["tumor_api/app/main.py"],
    )
    assert not project_matches_changed_paths(
        project,
        ["/home/zhuqin/project/zhenyuan/tumor_api"],
        ["tumor_html/src/App.vue"],
    )

    project.path_patterns = ["/work/zhenyuan/tumor_api/**"]
    assert project_matches_changed_paths(
        project,
        [],
        ["tumor_api/app/main.py"],
    )


@pytest.mark.asyncio
async def test_repository_scope_inherits_workspace_without_siblings() -> None:
    workspace = _project("zhenyuan-tumor-suite", "workspace")
    repository = _project("tumor_api", "repository")
    relation = ProjectRelation(
        user_id="user",
        parent_project_id=workspace.id,
        child_project_id=repository.id,
        relation_type="contains",
        status="active",
        source="manual",
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result([relation]),
            _result([workspace]),
            _result(
                [
                    _alias(repository.id, "legacy_id", "tumor-api-legacy"),
                    _alias(workspace.id, "name", "zhenyuan"),
                ]
            ),
        ]
    )

    scope = await project_context_scope(session, "user", repository, [])

    assert scope.canonical_project_ids == (repository.id, workspace.id)
    assert scope.inherited_project_ids == (workspace.id,)
    assert scope.selected_child_project_ids == ()
    assert set(scope.memory_scope_ids) == {
        repository.id,
        "tumor-api-legacy",
        workspace.id,
        "zhenyuan",
    }
    assert "tumor_html" not in scope.memory_scope_ids


@pytest.mark.asyncio
async def test_workspace_scope_selects_only_child_matching_changed_paths() -> None:
    workspace = _project("zhenyuan-tumor-suite", "workspace")
    api = _project("tumor_api", "repository")
    html = _project("tumor_html", "repository")
    relations = [
        ProjectRelation(
            user_id="user",
            parent_project_id=workspace.id,
            child_project_id=child.id,
            relation_type="contains",
            status="active",
            source="manual",
        )
        for child in (api, html)
    ]
    aliases = [
        _alias(api.id, "path", "/work/zhenyuan/tumor_api"),
        _alias(html.id, "path", "/work/zhenyuan/tumor_html"),
    ]
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result(relations),
            _result([api, html]),
            _result(aliases),
        ]
    )

    scope = await project_context_scope(
        session,
        "user",
        workspace,
        ["tumor_html/src/App.vue"],
    )

    assert scope.canonical_project_ids == (workspace.id, html.id)
    assert scope.selected_child_project_ids == (html.id,)
    assert api.id not in scope.memory_scope_ids


@pytest.mark.asyncio
async def test_workspace_scope_without_changed_paths_does_not_load_children() -> None:
    workspace = _project("zhenyuan-tumor-suite", "workspace")
    child = _project("tumor_api", "repository")
    relation = ProjectRelation(
        user_id="user",
        parent_project_id=workspace.id,
        child_project_id=child.id,
        relation_type="contains",
        status="active",
        source="manual",
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result([relation]),
            _result([child]),
            _result([_alias(child.id, "path", "/work/zhenyuan/tumor_api")]),
        ]
    )

    scope = await project_context_scope(session, "user", workspace, [])

    assert scope.canonical_project_ids == (workspace.id,)
    assert scope.selected_child_project_ids == ()


def test_memory_scope_tier_prioritizes_exact_then_inherited_over_global() -> None:
    scope = ProjectContextScope(
        exact_project_id="tumor_api",
        canonical_project_ids=("tumor_api", "zhenyuan-tumor-suite"),
        memory_scope_ids=("tumor_api", "suite-legacy"),
        inherited_project_ids=("zhenyuan-tumor-suite",),
        selected_child_project_ids=(),
        scope_ids_by_project={
            "tumor_api": ("tumor_api",),
            "zhenyuan-tumor-suite": ("suite-legacy", "zhenyuan-tumor-suite"),
        },
    )
    exact = Memory(title="Exact", content="x", scope_global=False, scope_projects=["tumor_api"])
    inherited = Memory(
        title="Shared",
        content="x",
        scope_global=False,
        scope_projects=["suite-legacy"],
    )
    global_memory = Memory(title="Global", content="x", scope_global=True, scope_projects=[])

    assert _memory_scope_tier(exact, scope) == (3, "exact_project")
    assert _memory_scope_tier(inherited, scope) == (2, "inherited_workspace")
    assert _memory_scope_tier(global_memory, scope) == (0, "global")


def test_relation_requires_workspace_parent_and_repository_child() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_relation_projects(
            _project("not-a-workspace", "repository"),
            _project("child", "repository"),
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_relation_create_and_archive_preserve_same_history_row() -> None:
    parent = _project("suite", "workspace")
    child = _project("repo", "repository")
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.add = MagicMock()

    async def flush() -> None:
        relation = session.add.call_args.args[0]
        if relation.id is None:
            relation.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        relation.created_at = relation.created_at or now
        relation.updated_at = relation.updated_at or now

    session.flush = AsyncMock(side_effect=flush)
    resolutions = AsyncMock(
        side_effect=[
            ProjectResolution(parent, "project_id", 1),
            ProjectResolution(child, "project_id", 1),
        ]
    )
    with patch("app.api.projects.resolve_project", new=resolutions):
        created = await create_project_relation(
            ProjectRelationCreate(parent_project_id=parent.id, child_project_id=child.id),
            session=session,
            user_id="user",
        )

    relation = session.add.call_args.args[0]
    assert created["status"] == "active"
    assert created["parent_project_id"] == parent.id

    session.scalar = AsyncMock(return_value=relation)
    archived = await update_project_relation(
        relation.id,
        ProjectRelationPatch(status="archived"),
        session=session,
        user_id="user",
    )

    assert archived["id"] == created["id"]
    assert archived["status"] == "archived"
