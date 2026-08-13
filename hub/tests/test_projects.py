"""Project deletion guards for Project Knowledge history."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.projects import delete_project


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
