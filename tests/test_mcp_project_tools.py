"""Contract tests for structured Project Knowledge MCP tools."""

import asyncio
import json

import httpx

from echome_mcp import hub_client
from echome_mcp import runtime as runtime_module
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
    assert by_name["echome_context"].outputSchema is not None
    assert by_name["echome_runtime_health"].annotations.readOnlyHint is True
    assert by_name["echome_context_outcome"].annotations.idempotentHint is True


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
    assert result.structuredContent["error"]["code"] == "INTERNAL_ERROR"
    assert result.structuredContent["error"]["request_id"]


def test_legacy_text_error_gets_structured_contract(monkeypatch) -> None:
    async def text_error(**_kwargs) -> str:
        return "Error: legacy tool failed"

    monkeypatch.setattr(server_module, "echome_search", text_error)
    result = asyncio.run(server_module.call_tool("echome_search", {"query": "test"}))

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "INTERNAL_ERROR"
    assert result.structuredContent["error"]["message"] == "Error: legacy tool failed"


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


def test_empty_runtime_exception_still_has_diagnostic_message() -> None:
    payload = runtime_module.error_contract(RuntimeError())

    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert payload["error"]["message"] == "RuntimeError"
    assert payload["error"]["request_id"]


def test_unified_context_returns_cached_read_only_result_on_hub_failure(
    monkeypatch, tmp_path
) -> None:
    payload = {
        "schema_version": "echome.context.v1",
        "scope": "personal",
        "task": "Git workflow",
        "memories": [{"id": "memory"}],
        "runtime": {"degraded": False},
    }

    class SuccessfulClient:
        cache_namespace = "test-user"
        cache_enabled = True

        async def unified_context(self, _data):
            return payload

    class FailingClient:
        cache_namespace = "test-user"
        cache_enabled = True

        async def unified_context(self, _data):
            raise httpx.ConnectError("offline")

    async def no_project_hint():
        return None

    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime_module, "_local_project_hint", no_project_hint)
    monkeypatch.setattr(runtime_module, "MCPHubClient", SuccessfulClient)
    first = json.loads(asyncio.run(runtime_module.echome_context("Git workflow")))
    cache_text = next(tmp_path.glob("*.json")).read_text()
    monkeypatch.setattr(runtime_module, "MCPHubClient", FailingClient)
    second = json.loads(asyncio.run(runtime_module.echome_context("Git workflow")))

    assert first["runtime"]["degraded"] is False
    assert "memory" not in cache_text
    assert second["runtime"]["degraded"] is True
    assert second["runtime"]["fallback"] == "last_known_good"
    assert second["degradation_error"]["code"] == "HUB_UNAVAILABLE"


def test_unified_context_does_not_use_cache_for_auth_failure(monkeypatch, tmp_path) -> None:
    payload = {"schema_version": "echome.context.v1", "runtime": {"degraded": False}}

    class SuccessfulClient:
        cache_namespace = "test-user"
        cache_enabled = True

        async def unified_context(self, _data):
            return payload

    class UnauthorizedClient:
        cache_namespace = "test-user"
        cache_enabled = True

        async def unified_context(self, _data):
            request = httpx.Request("POST", "http://hub/api/v1/context")
            response = httpx.Response(401, request=request, json={"detail": "expired"})
            raise httpx.HTTPStatusError("expired", request=request, response=response)

    async def no_project_hint():
        return None

    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime_module, "_local_project_hint", no_project_hint)
    monkeypatch.setattr(runtime_module, "MCPHubClient", SuccessfulClient)
    asyncio.run(runtime_module.echome_context("Git workflow"))
    monkeypatch.setattr(runtime_module, "MCPHubClient", UnauthorizedClient)

    result = json.loads(asyncio.run(runtime_module.echome_context("Git workflow")))

    assert result["error"]["code"] == "AUTH_FAILED"
    assert "runtime" not in result


def test_cache_write_failure_does_not_replace_online_context(monkeypatch) -> None:
    payload = {"schema_version": "echome.context.v1", "runtime": {"degraded": False}}

    class SuccessfulClient:
        cache_namespace = "test-user"
        cache_enabled = True

        async def unified_context(self, _data):
            return payload

    async def no_project_hint():
        return None

    def fail_cache(*_args):
        raise OSError("read-only cache")

    monkeypatch.setattr(runtime_module, "_local_project_hint", no_project_hint)
    monkeypatch.setattr(runtime_module, "MCPHubClient", SuccessfulClient)
    monkeypatch.setattr(runtime_module, "_cache_encryption_key", lambda: b"0" * 32)
    monkeypatch.setattr(runtime_module, "_write_cache", fail_cache)

    result = json.loads(asyncio.run(runtime_module.echome_context("Git workflow")))

    assert result == payload


def test_encrypted_context_cache_expires(monkeypatch, tmp_path) -> None:
    payload = {"task": "test"}
    context = {"memories": [{"content": "private"}]}
    key = b"1" * 32
    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_MAX_AGE_SECONDS", "10")
    monkeypatch.setattr(runtime_module, "time", lambda: 100)
    runtime_module._write_cache(payload, context, "user", key)
    monkeypatch.setattr(runtime_module, "time", lambda: 111)

    assert runtime_module._read_cache(payload, "user", key) is None


def test_existing_cache_key_permissions_are_tightened(monkeypatch, tmp_path) -> None:
    directory = tmp_path / "cache"
    directory.mkdir(mode=0o777)
    key_path = directory / ".key"
    key_path.write_bytes(b"2" * 32)
    key_path.chmod(0o644)
    directory.chmod(0o755)
    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(directory))

    assert runtime_module._cache_encryption_key() == b"2" * 32
    assert directory.stat().st_mode & 0o777 == 0o700
    assert key_path.stat().st_mode & 0o777 == 0o600


def test_core_profile_is_opt_in_and_keeps_default_context(monkeypatch) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "core")

    names = {tool.name for tool in asyncio.run(server_module.list_tools())}

    assert names == {
        "echome_capabilities",
        "echome_context",
        "echome_runtime_health",
        "echome_context_outcome",
        "echome_remember",
        "memory_remember",
        "echome_memory_feedback",
        "echome_memory_feedback_batch",
    }


def test_context_outcome_forwards_explicit_signal(monkeypatch) -> None:
    captured: dict = {}

    async def fake_outcome(**kwargs) -> str:
        captured.update(kwargs)
        return json.dumps({"id": "outcome-id", **kwargs})

    monkeypatch.setattr(server_module, "echome_context_outcome", fake_outcome)
    result = asyncio.run(
        server_module.call_tool(
            "echome_context_outcome",
            {
                "context_run_id": "11111111-1111-1111-1111-111111111111",
                "outcome": "success",
                "idempotency_key": "task-1",
            },
        )
    )

    assert result.isError is False
    assert captured["outcome"] == "success"
    assert captured["reported_by"] == "ai"
