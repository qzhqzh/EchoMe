"""Sync rendering status boundary tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.sync import render
from app.schemas.memory import RenderRequest


@pytest.mark.asyncio
async def test_static_render_selects_active_and_ai_review_memories() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    await render(RenderRequest(target="codex"), session=session, user_id="user")

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert ["active", "ai_review"] in compiled.params.values()
    assert "pending" not in compiled.params.values()
    assert "memories.status IN" in str(compiled)
