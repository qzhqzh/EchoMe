"""Canonical project identity and alias isolation tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.memory import Project
from app.models.project_knowledge import ProjectAlias
from app.services.project_identity import (
    canonicalize_project_scopes,
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

    result = await canonicalize_project_scopes(
        session, "user", ["legacy-alias", "unknown-project"]
    )

    assert result == ["canonical", "unknown-project"]
