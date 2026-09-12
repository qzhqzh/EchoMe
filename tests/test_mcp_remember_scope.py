"""Type and project scope are independent; remember never creates projects."""

from unittest.mock import AsyncMock

import httpx
import pytest

from echome_mcp.tools import remember


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", sorted(remember.VALID_TYPES))
async def test_every_type_retains_canonical_project_scope(monkeypatch, kind):
    client = AsyncMock()
    client.get_project.return_value = {"id": "OKB"}
    client.create_memory.return_value = {"id": "memory"}
    monkeypatch.setattr(remember, "MCPHubClient", lambda: client)
    result = await remember.echome_remember("Rule", "Verify evidence", kind, [], "L1", "legacy-okb")
    assert "Memory saved" in result
    payload = client.create_memory.call_args.args[0]
    assert payload["type"] == kind and payload["layer"] == "L1"
    assert payload["status"] == "ai_review"
    assert payload["scope"] == {"global": False, "projects": ["OKB"], "exclude_projects": []}
    client.create_project.assert_not_called()


@pytest.mark.asyncio
async def test_global_alias_and_missing_project_remain_compatible(monkeypatch):
    client = AsyncMock()
    client.create_memory.return_value = {"id": "memory"}
    monkeypatch.setattr(remember, "MCPHubClient", lambda: client)
    await remember.echome_remember("Rule", "Workflow", "workflow", [])
    payload = client.create_memory.call_args.args[0]
    assert payload["type"] == "method" and payload["scope"]["global"]
    client.get_project.assert_not_called()
    client.create_memory.reset_mock()
    await remember.echome_remember("Project", "Context", "project", [])
    client.create_memory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "ambiguous", "unauthorized"])
async def test_unresolved_or_unauthorized_project_cannot_write(monkeypatch, failure):
    client = AsyncMock()
    if failure == "unknown":
        client.get_project.return_value = None
    else:
        client.get_project.side_effect = httpx.HTTPStatusError(
            failure,
            request=httpx.Request("GET", "http://test/projects/hint"),
            response=httpx.Response(409 if failure == "ambiguous" else 401),
        )
    monkeypatch.setattr(remember, "MCPHubClient", lambda: client)
    await remember.echome_remember("Rule", "Content", "guardrail", [], "L1", "hint")
    client.create_memory.assert_not_called()
    client.create_project.assert_not_called()
