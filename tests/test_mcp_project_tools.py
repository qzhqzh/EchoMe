"""Contract tests for structured Project Knowledge MCP tools."""

import asyncio
import json

from echome_mcp import hub_client
from echome_mcp import server as server_module


def test_project_tools_advertise_structured_context_and_preflight() -> None:
    tools = asyncio.run(server_module.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert by_name["echome_project_context"].outputSchema is not None
    assert by_name["echome_project_context"].annotations.readOnlyHint is False
    assert by_name["echome_project_context"].annotations.idempotentHint is False
    assert by_name["echome_project_preflight"].outputSchema is not None
    assert by_name["echome_project_event_append"].annotations.readOnlyHint is False
    assert by_name["echome_project_event_append"].annotations.idempotentHint is False


def test_project_context_returns_text_and_structured_content(monkeypatch) -> None:
    payload = {
        "project": {"id": "demo"},
        "task": "check API",
        "constraints": [],
        "memories": [],
        "evidence": [],
    }

    async def fake_context(**_kwargs) -> str:
        return json.dumps(payload)

    monkeypatch.setattr(server_module, "echome_project_context", fake_context)
    result = asyncio.run(
        server_module.call_tool(
            "echome_project_context",
            {"project_id": "demo", "task": "check API"},
        )
    )

    assert result.isError is False
    assert result.structuredContent == payload
    assert json.loads(result.content[0].text) == payload


def test_project_context_failure_sets_protocol_error(monkeypatch) -> None:
    async def failing_context(**_kwargs) -> str:
        raise RuntimeError("hub unavailable")

    monkeypatch.setattr(server_module, "echome_project_context", failing_context)
    result = asyncio.run(
        server_module.call_tool(
            "echome_project_context",
            {"project_id": "demo", "task": "check API"},
        )
    )

    assert result.isError is True
    assert "hub unavailable" in result.content[0].text


def test_project_context_uses_extended_http_timeout(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"constraints": [], "memories": [], "evidence": []}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(hub_client.httpx, "AsyncClient", FakeClient)
    asyncio.run(hub_client.MCPHubClient().project_context("demo", "check API"))

    assert captured["timeout"].read == 120.0
