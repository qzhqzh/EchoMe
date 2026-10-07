import asyncio
import json
from uuid import uuid4

import pytest

from echome_mcp import server
from echome_mcp.tools import knowledge


def test_knowledge_tools_are_core_and_have_no_approval_action(monkeypatch):
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "core")
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert tools["echome_knowledge_read"].annotations.readOnlyHint
    assert not tools["echome_knowledge_write"].annotations.readOnlyHint
    assert tools["echome_knowledge_write"].inputSchema["properties"]["action"]["enum"] == [
        "create",
        "update",
    ]


def test_exact_query_and_context_adapter(monkeypatch):
    calls = []

    class FakeClient:
        async def knowledge_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"next_offset": None, "complete": True}

    monkeypatch.setattr(knowledge, "MCPHubClient", FakeClient)
    record_id = str(uuid4())
    filters = {"kind": "relation", "filters": {"subject_id": record_id}, "limit": 100}
    result = asyncio.run(knowledge.echome_knowledge_read("query", data=filters))
    assert json.loads(result)["complete"]
    asyncio.run(knowledge.echome_knowledge_read("context", record_id))
    assert calls[0] == ("POST", "/query", filters, None)
    assert calls[1][1] == "/records/" + record_id + "/context"
    with pytest.raises(ValueError):
        asyncio.run(knowledge.echome_knowledge_write("approve", {}))
    with pytest.raises(ValueError):
        asyncio.run(knowledge.echome_knowledge_read("get", "../agent-tokens"))
