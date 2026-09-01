"""Canonical project identity and alias isolation tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.memory import Project
from app.models.project_knowledge import ProjectAlias, ProjectRelation
from app.services.project_identity import (
    ProjectCandidate,
    ProjectDiscovery,
    ProjectResolution,
    canonicalize_project_scopes,
    discover_projects,
    ensure_project_aliases,
    normalize_project_hint,
    project_scope_ids,
    resolve_project,
    update_project_git_identity,
)


def _scalar_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def test_git_remote_normalization_matches_ssh_and_https() -> None:
    normalized = normalize_project_hint(
        "git@github.com:qzhqzh/EchoMe.git", "git_remote"
    )
    assert normalized == normalize_project_hint(
        "https://github.com/qzhqzh/EchoMe", "git_remote"
    )
    assert normalized == normalize_project_hint(
        "ssh://git@github.com/qzhqzh/EchoMe.git", "git_remote"
    )


@pytest.mark.asyncio
async def test_https_git_alias_resolves_scp_style_ssh_remote() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    alias = ProjectAlias(
        id=uuid.uuid4(),
        user_id="user",
        canonical_project_id=project.id,
        alias_type="git_remote",
        alias_value="https://github.com/owner/repo.git",
        normalized_value="github.com/owner/repo",
        status="active",
        source="ai",
        confidence=1.0,
    )
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, project])
    session.execute = AsyncMock(return_value=_scalar_result([alias]))

    resolution = await resolve_project(session, "user", "git@github.com:owner/repo.git")

    assert resolution.project.id == project.id
    assert resolution.matched_by == "alias:git_remote"


@pytest.mark.asyncio
async def test_ensure_project_aliases_creates_activates_and_skips_covered_identity() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        git_remote="https://github.com/owner/repo.git",
        path_patterns=["/srv/repo/**"],
    )
    existing = ProjectAlias(
        id=uuid.uuid4(),
        user_id="user",
        canonical_project_id=project.id,
        alias_type="name",
        alias_value="repo-dev",
        normalized_value="repo-dev",
        status="proposed",
        source="ai",
        confidence=0.7,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([existing]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
    ):
        result = await ensure_project_aliases(
            session,
            "user",
            project.id,
            [
                ("legacy_id", "owner/repo-dev"),
                ("name", "repo-dev"),
                ("git_remote", "git@github.com:owner/repo.git"),
                ("path", "/srv/repo"),
            ],
            confidence=0.9,
        )

    payload = result.payload()
    assert payload["status"] == "updated"
    assert [item["outcome"] for item in payload["items"]] == [
        "created",
        "activated",
        "covered_by_project",
        "covered_by_project",
    ]
    created = session.add.call_args.args[0]
    assert created.canonical_project_id == project.id
    assert created.alias_type == "legacy_id"
    assert created.status == "active"
    assert existing.status == "active"
    assert existing.confidence == 0.9
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_project_aliases_is_idempotent_for_active_alias() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    existing = ProjectAlias(
        id=uuid.uuid4(),
        user_id="user",
        canonical_project_id=project.id,
        alias_type="legacy_id",
        alias_value="owner/repo-dev",
        normalized_value="owner/repo-dev",
        status="active",
        source="ai",
        confidence=0.9,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([existing]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
    ):
        result = await ensure_project_aliases(
            session,
            "user",
            project.id,
            [("legacy_id", "owner/repo-dev")],
        )

    assert result.payload()["status"] == "unchanged"
    assert result.payload()["items"][0]["outcome"] == "unchanged"
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_project_aliases_rejects_cross_project_primary_conflict_atomically() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    other = Project(
        id="other/repo",
        user_id="user",
        name="other",
        kind="repository",
        git_remote="https://github.com/other/repo.git",
        path_patterns=[],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project, other]),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await ensure_project_aliases(
            session,
            "user",
            project.id,
            [
                ("legacy_id", "owner/repo-dev"),
                ("git_remote", "git@github.com:other/repo.git"),
            ],
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PROJECT_ALIAS_CONFLICT"
    assert exc_info.value.detail["canonical_project_ids"] == [other.id]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_project_aliases_rejects_cross_type_active_alias_conflict() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    other = Project(
        id="other/repo",
        user_id="user",
        name="other",
        kind="repository",
        path_patterns=[],
    )
    other_alias = ProjectAlias(
        id=uuid.uuid4(),
        user_id="user",
        canonical_project_id=other.id,
        alias_type="name",
        alias_value="repo-dev",
        normalized_value="repo-dev",
        status="active",
        source="ai",
        confidence=0.8,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([other_alias]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project, other]),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await ensure_project_aliases(
            session,
            "user",
            project.id,
            [("legacy_id", "repo-dev")],
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["canonical_project_ids"] == [other.id]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_resolved_discovery_offers_confirmed_primary_git_identity_update() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    discovery = ProjectDiscovery(
        status="resolved",
        hints=("git@github.com:owner/repo.git",),
        candidates=(
            ProjectCandidate(
                project=project,
                confidence=0.8,
                matched_by=("repository_basename",),
                matched_hints=("git@github.com:owner/repo.git",),
            ),
        ),
        resolution=ProjectResolution(project, "project_id", 1.0),
    )

    update_action = next(
        action
        for action in discovery.payload()["next_actions"]
        if action["action"] == "confirm_then_update_project_git_identity"
    )

    assert update_action["arguments"] == {
        "project_id": "owner/repo",
        "confirmed": False,
        "git_remote": "git@github.com:owner/repo.git",
    }


@pytest.mark.asyncio
async def test_git_identity_preview_does_not_mutate_project() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
    ):
        result = await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote="git@github.com:owner/repo.git",
            git_remote_aliases=[],
            confirmed=False,
        )

    payload = result.payload()
    assert payload["status"] == "confirmation_required"
    assert payload["requires_confirmation"] is True
    assert len(payload["confirmation_token"]) == 64
    assert payload["project"]["git_remote"] is None
    assert payload["changes"]["git_remote"]["after"] == "git@github.com:owner/repo.git"
    assert project.git_remote is None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_git_identity_update_sets_remote_and_adds_active_alias() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
    ):
        preview = await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote="git@github.com:owner/repo.git",
            git_remote_aliases=["ssh://git@mirror.example.com/owner/repo.git"],
            confirmed=False,
        )
        result = await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote="git@github.com:owner/repo.git",
            git_remote_aliases=["ssh://git@mirror.example.com/owner/repo.git"],
            confirmed=True,
            confirmation_token=preview.confirmation_token,
        )

    payload = result.payload()
    assert payload["status"] == "updated"
    assert project.git_remote == "git@github.com:owner/repo.git"
    created_alias = session.add.call_args.args[0]
    assert created_alias.canonical_project_id == project.id
    assert created_alias.alias_type == "git_remote"
    assert created_alias.status == "active"
    assert created_alias.source == "ai"
    assert created_alias.confidence == 1.0
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_equivalent_ssh_alias_is_covered_by_https_primary() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        git_remote="https://github.com/owner/repo.git",
        path_patterns=[],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
    ):
        result = await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote=None,
            git_remote_aliases=["git@github.com:owner/repo.git"],
            confirmed=True,
        )

    payload = result.payload()
    assert payload["status"] == "unchanged"
    assert payload["changes"]["aliases_covered_by_primary"] == [
        "git@github.com:owner/repo.git"
    ]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_git_identity_update_activates_existing_alias() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    alias = ProjectAlias(
        user_id="user",
        canonical_project_id=project.id,
        alias_type="git_remote",
        alias_value="git@github.com:owner/repo.git",
        normalized_value="github.com/owner/repo",
        status="proposed",
        source="ai",
        confidence=0.8,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([alias]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
    ):
        preview = await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote=None,
            git_remote_aliases=["ssh://git@github.com/owner/repo.git"],
            confirmed=False,
        )
        result = await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote=None,
            git_remote_aliases=["ssh://git@github.com/owner/repo.git"],
            confirmed=True,
            confirmation_token=preview.confirmation_token,
        )

    assert result.payload()["status"] == "updated"
    assert alias.status == "active"
    session.add.assert_not_called()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirmed_git_identity_update_requires_latest_preview_token() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote="git@github.com:owner/repo.git",
            git_remote_aliases=[],
            confirmed=True,
            confirmation_token="0" * 64,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PROJECT_GIT_IDENTITY_PREVIEW_REQUIRED"
    assert project.git_remote is None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_git_identity_update_rejects_another_projects_remote() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    other_project = Project(
        id="other/repo",
        user_id="user",
        name="other",
        kind="repository",
        git_remote="https://github.com/other/repo.git",
        path_patterns=[],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project, other_project]),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote="git@github.com:other/repo.git",
            git_remote_aliases=[],
            confirmed=True,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PROJECT_GIT_IDENTITY_CONFLICT"
    assert exc_info.value.detail["canonical_project_ids"] == [other_project.id]
    assert project.git_remote is None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_git_identity_update_rejects_alias_owned_by_another_project() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    conflicting_alias = ProjectAlias(
        user_id="user",
        canonical_project_id="other/repo",
        alias_type="git_remote",
        alias_value="https://github.com/other/repo.git",
        normalized_value="github.com/other/repo",
        status="active",
        source="manual",
        confidence=1.0,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result([conflicting_alias]))
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.project_identity.resolve_project",
            new=AsyncMock(return_value=ProjectResolution(project, "project_id", 1.0)),
        ),
        patch(
            "app.services.project_identity._all_user_projects",
            new=AsyncMock(return_value=[project]),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await update_project_git_identity(
            session,
            "user",
            project.id,
            git_remote=None,
            git_remote_aliases=["git@github.com:other/repo.git"],
            confirmed=False,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["canonical_project_ids"] == ["other/repo"]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_auto_resolves_unique_environment_path_variant() -> None:
    project = Project(
        id="bycrm",
        user_id="user",
        name="bycrm",
        kind="repository",
        path_patterns=[],
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result([project]),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Project not found")),
    ):
        discovery = await discover_projects(session, "user", ["/srv/bycrm-dev"])

    assert discovery.status == "resolved"
    assert discovery.resolution is not None
    assert discovery.resolution.project.id == "bycrm"
    assert discovery.resolution.matched_by.startswith("discovery:")
    assert discovery.payload()["auto_resolved"] is True


@pytest.mark.asyncio
async def test_discovery_refuses_to_guess_between_environment_variants() -> None:
    projects = [
        Project(
            id=project_id,
            user_id="user",
            name=project_id,
            kind="repository",
            path_patterns=[],
        )
        for project_id in ("client-dev", "client-prod")
    ]
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(projects),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Project not found")),
    ):
        discovery = await discover_projects(session, "user", ["client-local"], limit=1)

    assert discovery.status == "ambiguous"
    assert discovery.resolution is None
    assert [candidate.project.id for candidate in discovery.candidates] == [
        "client-dev",
        "client-prod",
    ]


@pytest.mark.asyncio
async def test_discovery_does_not_auto_resolve_short_generic_basename() -> None:
    project = Project(
        id="api",
        user_id="user",
        name="api",
        kind="repository",
        path_patterns=[],
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result([project]),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Project not found")),
    ):
        discovery = await discover_projects(session, "user", ["/srv/api"])

    assert discovery.status == "needs_confirmation"
    assert discovery.resolution is None
    assert discovery.candidates[0].project.id == "api"


@pytest.mark.asyncio
async def test_discovery_surfaces_matching_workspace_ecosystem() -> None:
    workspace = Project(
        id="qmo",
        user_id="user",
        name="Qmo workspace",
        kind="workspace",
        path_patterns=[],
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result([workspace]),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Project not found")),
    ):
        discovery = await discover_projects(session, "user", ["/srv/qmo_api"])

    assert discovery.status == "needs_confirmation"
    assert discovery.candidates[0].project.id == "qmo"
    assert "workspace_identity_token" in discovery.candidates[0].matched_by


@pytest.mark.asyncio
async def test_discovery_offers_parent_workspace_retry_for_repository_candidate() -> None:
    workspace = Project(
        id="qmo",
        user_id="user",
        name="Qmo workspace",
        kind="workspace",
        path_patterns=[],
    )
    repository = Project(
        id="api",
        user_id="user",
        name="api",
        kind="repository",
        path_patterns=[],
    )
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
            _scalar_result([workspace, repository]),
            _scalar_result([]),
            _scalar_result([relation]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Project not found")),
    ):
        discovery = await discover_projects(session, "user", ["/srv/api"])

    retry_ids = {
        action["arguments"]["project_hint"]
        for action in discovery.payload()["next_actions"]
        if action["action"] == "retry_context"
    }
    assert retry_ids == {"api", "qmo"}


@pytest.mark.asyncio
async def test_discovery_refuses_conflicting_exact_signals() -> None:
    projects = [
        Project(
            id=project_id,
            user_id="user",
            name=project_id,
            kind="repository",
            path_patterns=[],
        )
        for project_id in ("remote-project", "path-project")
    ]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(projects))

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(
            side_effect=[
                ProjectResolution(projects[0], "project_git_remote", 0.95),
                ProjectResolution(projects[1], "project_path_pattern", 0.85),
            ]
        ),
    ):
        discovery = await discover_projects(
            session,
            "user",
            ["git@example.com:owner/remote-project.git", "/srv/path-project"],
        )

    assert discovery.status == "ambiguous"
    assert discovery.resolution is None
    assert {candidate.project.id for candidate in discovery.candidates} == {
        "remote-project",
        "path-project",
    }


@pytest.mark.asyncio
async def test_discovery_detects_strong_conflict_after_one_exact_signal() -> None:
    old_remote = Project(
        id="old-project",
        user_id="user",
        name="old-project",
        kind="repository",
        path_patterns=[],
    )
    current_path = Project(
        id="current",
        user_id="user",
        name="current",
        kind="repository",
        path_patterns=[],
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result([old_remote, current_path]),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(
            side_effect=[
                ProjectResolution(old_remote, "project_git_remote", 0.95),
                HTTPException(status_code=404, detail="Project not found"),
            ]
        ),
    ):
        discovery = await discover_projects(
            session,
            "user",
            ["git@example.com:owner/old-project.git", "/srv/current-dev"],
        )

    assert discovery.status == "ambiguous"
    assert discovery.resolution is None
    assert {candidate.project.id for candidate in discovery.candidates} == {
        "old-project",
        "current",
    }


@pytest.mark.asyncio
async def test_discovery_returns_silent_create_proposal_only_after_no_match() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )

    with patch(
        "app.services.project_identity.resolve_project",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Project not found")),
    ):
        discovery = await discover_projects(
            session,
            "user",
            ["git@github.com:owner/new-repo.git", "/srv/new-repo"],
        )

    payload = discovery.payload()
    assert discovery.status == "not_found"
    assert payload["requires_confirmation"] is False
    assert payload["create_proposal"]["project_id"] == "owner/new-repo"
    assert payload["create_proposal"]["path_patterns"] == ["/srv/new-repo/**"]
    assert payload["next_actions"][0]["action"] == "create_project"


def test_discovery_single_candidate_offers_silent_alias_attachment() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    discovery = ProjectDiscovery(
        status="needs_confirmation",
        hints=("owner/repo-dev",),
        candidates=(
            ProjectCandidate(
                project=project,
                confidence=0.8,
                matched_by=("project_name:environment_variant",),
                matched_hints=("owner/repo-dev",),
            ),
        ),
    )

    payload = discovery.payload()

    assert payload["requires_confirmation"] is False
    attach_action = next(
        action
        for action in payload["next_actions"]
        if action["action"] == "create_or_attach_project"
    )
    assert attach_action["arguments"]["project_id"] == "owner/repo-dev"


@pytest.mark.asyncio
async def test_active_alias_resolves_to_same_users_canonical_project() -> None:
    project = Project(id="qzhqzh/EchoMe", user_id="user", name="EchoMe")
    alias = ProjectAlias(
        id=uuid.uuid4(),
        user_id="user",
        canonical_project_id=project.id,
        alias_type="legacy_id",
        alias_value="EchoMe",
        normalized_value="echome",
        status="active",
        source="manual",
        confidence=1,
    )
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, project])
    session.execute = AsyncMock(return_value=_scalar_result([alias]))

    resolution = await resolve_project(session, "user", "EchoMe")

    assert resolution.project.id == "qzhqzh/EchoMe"
    assert resolution.matched_by == "alias:legacy_id"


@pytest.mark.asyncio
async def test_alias_lookup_is_scoped_to_user() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock(side_effect=[_scalar_result([]), _scalar_result([])])

    with pytest.raises(HTTPException) as exc_info:
        await resolve_project(session, "other-user", "EchoMe")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_ambiguous_aliases_are_rejected_instead_of_guessed() -> None:
    aliases = [
        ProjectAlias(
            user_id="user",
            canonical_project_id=project_id,
            alias_type=alias_type,
            alias_value="EchoMe",
            normalized_value="echome",
            status="active",
            source="manual",
            confidence=1,
        )
        for project_id, alias_type in (
            ("qzhqzh/EchoMe", "legacy_id"),
            ("archived/EchoMe", "name"),
        )
    ]
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=_scalar_result(aliases))

    with pytest.raises(HTTPException) as exc_info:
        await resolve_project(session, "user", "EchoMe")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AMBIGUOUS_PROJECT_HINT"


@pytest.mark.asyncio
async def test_scope_expansion_excludes_remote_and_path_alias_values() -> None:
    aliases = [
        ProjectAlias(
            user_id="user",
            canonical_project_id="qzhqzh/EchoMe",
            alias_type=alias_type,
            alias_value=value,
            normalized_value=value.casefold(),
            status="active",
            source="manual",
            confidence=1,
        )
        for alias_type, value in (
            ("legacy_id", "EchoMe"),
            ("git_remote", "github.com/qzhqzh/echome"),
            ("path", "/srv/EchoMe"),
        )
    ]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(aliases[:1]))

    values = await project_scope_ids(session, "user", "qzhqzh/EchoMe")

    assert values == ["EchoMe", "qzhqzh/EchoMe"]


@pytest.mark.asyncio
async def test_write_scopes_use_canonical_project_and_preserve_unknown_legacy_id() -> None:
    canonical = Project(id="canonical", user_id="user", name="EchoMe", path_patterns=[])
    alias = ProjectAlias(
        user_id="user",
        canonical_project_id="canonical",
        alias_type="legacy_id",
        alias_value="legacy-alias",
        normalized_value="legacy-alias",
        status="active",
        source="manual",
        confidence=1,
    )
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, canonical, None])
    session.execute = AsyncMock(
        side_effect=[_scalar_result([alias]), _scalar_result([]), _scalar_result([])]
    )

    result = await canonicalize_project_scopes(session, "user", ["legacy-alias", "unknown-project"])

    assert result == ["canonical", "unknown-project"]
