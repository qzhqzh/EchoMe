"""Canonical project identity and alias isolation tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.memory import Project
from app.models.project_knowledge import ProjectAlias, ProjectRelation
from app.services.project_identity import (
    ProjectResolution,
    canonicalize_project_scopes,
    discover_projects,
    normalize_project_hint,
    project_scope_ids,
    resolve_project,
)


def _scalar_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def test_git_remote_normalization_matches_ssh_and_https() -> None:
    assert normalize_project_hint(
        "git@github.com:qzhqzh/EchoMe.git", "git_remote"
    ) == normalize_project_hint("https://github.com/qzhqzh/EchoMe", "git_remote")


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
        discovery = await discover_projects(session, "user", ["client-local"])

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
async def test_discovery_returns_confirmed_create_proposal_only_after_no_match() -> None:
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
    assert payload["requires_confirmation"] is True
    assert payload["create_proposal"]["project_id"] == "owner/new-repo"
    assert payload["create_proposal"]["path_patterns"] == ["/srv/new-repo/**"]
    assert payload["next_actions"][0]["action"] == "confirm_then_create_project"


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
