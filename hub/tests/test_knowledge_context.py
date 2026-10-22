"""Discovery remains bounded and does not fetch entire knowledge documents."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.knowledge_context import discover_knowledge_refs


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?! % _", "123 456", "如何", "知识", "the and for"])
async def test_empty_or_generic_discovery_never_queries_database(query: str) -> None:
    session = AsyncMock()
    assert await discover_knowledge_refs(session, user_id="owner", query=query) == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id", [None, "resolved-project"])
async def test_discovery_uses_two_owner_scoped_bounded_projections(project_id: str | None) -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result
    await discover_knowledge_refs(
        session,
        user_id="owner",
        query=" ".join(f"token{number}" for number in range(100)),
        project_id=project_id,
        limit=1000,
    )
    assert session.execute.await_count == 2
    statements = [call.args[0] for call in session.execute.await_args_list]
    sql = [
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in statements
    ]
    assert all("LIMIT 4" in statement for statement in sql)
    assert all("left(" in statement for statement in sql)
    assert "knowledge_records.user_id = 'owner'" in sql[0]
    assert "scene_knowledge.user_id = 'owner'" in sql[1]
    assert "scene_knowledge_entries.user_id = 'owner'" in sql[1]
    assert "scene_knowledge.project_id IS NULL" in sql[1]
    assert ("scene_knowledge.project_id = 'resolved-project'" in sql[1]) == bool(project_id)
    assert "knowledge_references.owner_revision = knowledge_records_1.revision" in sql[0]
    for statement in statements:
        assert "payload" not in statement.selected_columns
        assert "content" not in statement.selected_columns
        patterns = {
            value
            for value in statement.compile().params.values()
            if isinstance(value, str) and value.startswith("%")
        }
        assert 0 < len(patterns) <= 24


@pytest.mark.asyncio
async def test_disabled_discovery_never_queries_database() -> None:
    session = AsyncMock()
    assert await discover_knowledge_refs(session, user_id="owner", query="Blender", limit=0) == []
    session.execute.assert_not_called()
