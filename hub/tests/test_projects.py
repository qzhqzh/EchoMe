"""Project deletion guards for Project Knowledge history."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.projects import (
    ProjectGitIdentityUpdateRequest,
    delete_project,
    patch_project_git_identity,
)
from app.models.memory import Project
from app.services.project_identity import ProjectGitIdentityUpdate


@pytest.mark.asyncio
async def test_git_identity_endpoint_returns_server_owned_preview() -> None:
    project = Project(
        id="owner/repo",
        user_id="user",
        name="repo",
        kind="repository",
        path_patterns=[],
    )
    preview = ProjectGitIdentityUpdate(
        project=project,
        before_git_remote=None,
        requested_git_remote="git@github.com:owner/repo.git",
        normalized_git_remote="github.com/owner/repo",
        aliases_to_create=(),
        aliases_to_activate=(),
        aliases_unchanged=(),
        aliases_covered_by_primary=(),
        applied=False,
    )
    body = ProjectGitIdentityUpdateRequest(
        project_id=project.id,
        git_remote="git@github.com:owner/repo.git",
    )
    session = AsyncMock()

    with patch(
        "app.api.projects.update_project_git_identity",
        new=AsyncMock(return_value=preview),
    ) as update:
        payload = await patch_project_git_identity(body, session=session, user_id="user")

    assert payload["status"] == "confirmation_required"
    update.assert_awaited_once_with(
        session,
        "user",
        project.id,
        git_remote="git@github.com:owner/repo.git",
        git_remote_aliases=[],
        confirmed=False,
        confirmation_token=None,
        source="ai",
    )


@pytest.mark.asyncio
async def test_delete_project_returns_conflict_for_context_history() -> None:
    project = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.scalar = AsyncMock(side_effect=[project, None, None, None, uuid.uuid4()])

    with pytest.raises(HTTPException) as exc_info:
        await delete_project("qzhqzh/EchoMe", session=session, user_id="user")

    assert exc_info.value.status_code == 409
    session.delete.assert_not_awaited()
