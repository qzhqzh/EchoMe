"""Contract tests for structured Project Knowledge MCP tools."""

import asyncio
import json

import httpx

from echome_mcp import hub_client
from echome_mcp import runtime as runtime_module
from echome_mcp import server as server_module
from echome_mcp.tools import project as project_tools_module
from echome_mcp.tools.capabilities import capabilities_payload


def test_project_tools_advertise_structured_context_and_preflight(monkeypatch) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "full")
    tools = asyncio.run(server_module.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert by_name["echome_project_context"].outputSchema is not None
    assert by_name["echome_project_context"].outputSchema["type"] == "object"
    assert "anyOf" in by_name["echome_project_context"].outputSchema
    assert by_name["echome_project_context"].annotations.readOnlyHint is False
    assert by_name["echome_project_context"].annotations.idempotentHint is False
    assert by_name["echome_project_preflight"].outputSchema is not None
    assert by_name["echome_project_preflight"].outputSchema["type"] == "object"
    assert "anyOf" in by_name["echome_project_preflight"].outputSchema
    assert by_name["echome_project_event_append"].annotations.readOnlyHint is False
    assert by_name["echome_project_event_append"].annotations.idempotentHint is False
    assert by_name["echome_context"].outputSchema is not None
    assert "project_hints" in by_name["echome_context"].inputSchema["properties"]
    assert by_name["echome_context"].inputSchema["properties"]["policy_mode"]["default"] == "shadow"
    assert (
        by_name["echome_project_context"].inputSchema["properties"]["policy_mode"]["default"]
        == "shadow"
    )
    assert (
        by_name["echome_sleep_candidates"].inputSchema["properties"]["plan_schema_version"][
            "default"
        ]
        == "memory_sleep_plan.v2"
    )
    assert by_name["echome_runtime_health"].annotations.readOnlyHint is True
    assert (
        by_name["echome_runtime_health"].inputSchema["properties"]["include_policy_readiness"][
            "default"
        ]
        is False
    )
    assert by_name["echome_context_outcome"].annotations.idempotentHint is True
    assert "policy_effect" in by_name["echome_context_outcome"].inputSchema["properties"]
    assert by_name["echome_reflect_prepare"].annotations.readOnlyHint is True
    assert by_name["echome_reflect_submit"].annotations.readOnlyHint is False
    assert by_name["echome_reflect_submit"].annotations.idempotentHint is True
    assert by_name["echome_reflect_submit"].inputSchema["properties"]["claims"]["minItems"] == 1
    assert "content" not in by_name["echome_reflect_submit"].inputSchema["properties"]
    assert (
        by_name["echome_create_project"].inputSchema["properties"][
            "confirmed_distinct_project"
        ]["default"]
        is False
    )


def test_create_project_stops_when_discovery_finds_existing_candidate(monkeypatch) -> None:
    class CandidateClient:
        async def discover_projects(self, _hints):
            return {
                "status": "needs_confirmation",
                "candidates": [{"project": {"id": "owner/existing"}}],
            }

        async def get_project(self, _project_id):
            raise AssertionError("exact lookup must not run after a discovery match")

        async def create_project(self, **_kwargs):
            raise AssertionError("project must not be created while a candidate exists")

    monkeypatch.setattr(project_tools_module, "MCPHubClient", CandidateClient)

    result = asyncio.run(
        project_tools_module.echome_create_project(
            name="existing-dev",
            git_remote="git@example.com:owner/existing.git",
        )
    )

    assert "未创建项目" in result
    assert "owner/existing" in result


def test_all_structured_tool_outputs_have_object_root_for_client_compatibility(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "full")

    for tool in asyncio.run(server_module.list_tools()):
        if tool.outputSchema is not None:
            assert tool.outputSchema.get("type") == "object", tool.name


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


def test_project_resolution_envelope_is_not_a_protocol_error(monkeypatch) -> None:
    payload = {
        "schema_version": "echome.context.v1",
        "scope": "project_resolution",
        "project_resolution": {
            "schema_version": "echome.project-resolution.v1",
            "status": "not_found",
            "next_actions": [{"action": "confirm_then_create_project"}],
        },
        "runtime": {"resolution_required": True},
    }

    async def fake_context(**_kwargs) -> str:
        return json.dumps(payload)

    monkeypatch.setattr(server_module, "echome_context", fake_context)
    result = asyncio.run(
        server_module.call_tool(
            "echome_context",
            {"task": "inspect unknown project", "project_hint": "unknown"},
        )
    )

    assert result.isError is False
    assert result.structuredContent == payload


def test_mcp_context_policy_and_sleep_schema_are_forwarded(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    async def fake_context(**kwargs) -> str:
        captured["context"] = kwargs
        return json.dumps({"schema_version": "echome.context.v1"})

    async def fake_project_context(**kwargs) -> str:
        captured["project_context"] = kwargs
        return json.dumps({"schema_version": "echome.context.v1"})

    async def fake_sleep_candidates(**kwargs) -> str:
        captured["sleep_candidates"] = kwargs
        return json.dumps({"schema_version": kwargs["plan_schema_version"]})

    monkeypatch.setattr(server_module, "echome_context", fake_context)
    monkeypatch.setattr(server_module, "echome_project_context", fake_project_context)
    monkeypatch.setattr(server_module, "echome_sleep_candidates", fake_sleep_candidates)

    asyncio.run(
        server_module.call_tool(
            "echome_context",
            {
                "task": "check reliability",
                "project_hints": ["repo", "/srv/repo"],
                "policy_mode": "enforce",
            },
        )
    )
    asyncio.run(
        server_module.call_tool(
            "echome_project_context",
            {"project_id": "demo", "task": "check reliability"},
        )
    )
    asyncio.run(server_module.call_tool("echome_sleep_candidates", {}))

    assert captured["context"]["policy_mode"] == "enforce"
    assert captured["context"]["project_hints"] == ["repo", "/srv/repo"]
    assert captured["project_context"]["policy_mode"] == "shadow"
    assert captured["sleep_candidates"]["plan_schema_version"] == "memory_sleep_plan.v2"


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


def test_reflection_tools_forward_prepare_contract_and_claims(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    async def fake_prepare(**kwargs) -> str:
        captured["prepare"] = kwargs
        return json.dumps({"read_only": True, "source_watermark": {"source_fingerprint": "fp"}})

    async def fake_submit(**kwargs) -> str:
        captured["submit"] = kwargs
        return json.dumps({"source_fingerprint_verified": True})

    monkeypatch.setattr(server_module, "echome_reflect_prepare", fake_prepare)
    monkeypatch.setattr(server_module, "echome_reflect_submit", fake_submit)
    source_id = "11111111-1111-1111-1111-111111111111"
    watermark = {"schema_version": "echome.reflect.v1", "source_fingerprint": "fp"}
    claims = [
        {
            "statement": "Supported claim",
            "confidence": 0.9,
            "evidence_refs": [{"target_type": "memory", "target_id": source_id}],
        }
    ]

    asyncio.run(
        server_module.call_tool(
            "echome_reflect_prepare",
            {"project_id": "demo", "query": "architecture"},
        )
    )
    asyncio.run(
        server_module.call_tool(
            "echome_reflect_submit",
            {
                "project_id": "demo",
                "query": "architecture",
                "claims": claims,
                "source_watermark": watermark,
                "idempotency_key": "reflect-task-1",
            },
        )
    )

    assert captured["prepare"]["token_budget"] == 12000
    assert captured["submit"]["claims"] == claims
    assert captured["submit"]["source_watermark"] == watermark
    assert captured["submit"]["idempotency_key"] == "reflect-task-1"


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


def test_runtime_error_preserves_hub_project_error_code_and_action() -> None:
    request = httpx.Request("POST", "http://hub/api/v1/context")
    response = httpx.Response(
        404,
        request=request,
        json={
            "schema_version": "echome.error.v1",
            "error": {
                "code": "PROJECT_NOT_FOUND",
                "message": "No canonical project matched",
                "suggested_action": "Retry with a candidate project ID.",
            },
        },
    )

    payload = runtime_module.error_contract(
        httpx.HTTPStatusError("not found", request=request, response=response)
    )

    assert payload["error"]["code"] == "PROJECT_NOT_FOUND"
    assert payload["error"]["suggested_action"] == "Retry with a candidate project ID."


def test_unified_context_forwards_all_local_project_identity_signals(monkeypatch) -> None:
    captured: dict = {}

    class SuccessfulClient:
        cache_namespace = "test-user"
        cache_enabled = False

        async def unified_context(self, data):
            captured.update(data)
            return {"schema_version": "echome.context.v1", "runtime": {"degraded": False}}

    async def local_project_hints():
        return ["git@example.com:owner/repo.git", "/srv/repo"]

    monkeypatch.setattr(runtime_module, "_local_project_hints", local_project_hints)
    monkeypatch.setattr(runtime_module, "MCPHubClient", SuccessfulClient)

    asyncio.run(runtime_module.echome_context("inspect project"))

    assert captured["project_hint"] == "git@example.com:owner/repo.git"
    assert captured["project_hints"] == ["/srv/repo"]


def test_local_project_hints_continue_to_repository_root_without_origin(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self, stdout: bytes, returncode: int) -> None:
            self._stdout = stdout
            self.returncode = returncode

        async def communicate(self):
            return self._stdout, b""

    async def create_process(_git, *arguments, **_kwargs):
        if arguments[0] == "config":
            return FakeProcess(b"", 1)
        return FakeProcess(b"/srv/repo\n", 0)

    monkeypatch.setattr(runtime_module.asyncio, "create_subprocess_exec", create_process)

    hints = asyncio.run(runtime_module._local_project_hints())

    assert hints == ["/srv/repo"]


def test_unresolved_project_context_is_not_written_as_last_known_good(monkeypatch) -> None:
    class ResolutionClient:
        cache_namespace = "test-user"
        cache_enabled = True

        async def unified_context(self, _data):
            return {
                "schema_version": "echome.context.v1",
                "scope": "project_resolution",
                "runtime": {"degraded": False, "resolution_required": True},
            }

    async def local_project_hints():
        return ["unknown-project"]

    def unexpected_cache_write(*_args):
        raise AssertionError("unresolved project recovery must not be cached")

    monkeypatch.setattr(runtime_module, "_local_project_hints", local_project_hints)
    monkeypatch.setattr(runtime_module, "MCPHubClient", ResolutionClient)
    monkeypatch.setattr(runtime_module, "_cache_encryption_key", lambda: b"0" * 32)
    monkeypatch.setattr(runtime_module, "_write_cache", unexpected_cache_write)

    payload = json.loads(asyncio.run(runtime_module.echome_context("inspect project")))

    assert payload["scope"] == "project_resolution"


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

    async def no_project_hints():
        return []

    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime_module, "_local_project_hints", no_project_hints)
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
    assert second["completion_contract"]["report_outcome"] is False
    assert second["completion_contract"]["required_at_task_end"] is False


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

    async def no_project_hints():
        return []

    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime_module, "_local_project_hints", no_project_hints)
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

    async def no_project_hints():
        return []

    def fail_cache(*_args):
        raise OSError("read-only cache")

    monkeypatch.setattr(runtime_module, "_local_project_hints", no_project_hints)
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


def test_explicit_core_profile_keeps_graph_reliability(monkeypatch) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "core")

    names = {tool.name for tool in asyncio.run(server_module.list_tools())}

    assert names == {
        "echome_capabilities",
        "echome_context",
        "echome_runtime_health",
        "echome_context_outcome",
        "echome_memory_explain",
        "echome_remember",
        "echome_create_project",
        "echome_memory_feedback",
        "echome_memory_feedback_batch",
    }


def test_full_profile_preserves_specialized_tools(monkeypatch) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "full")

    names = {tool.name for tool in asyncio.run(server_module.list_tools())}

    assert "echome_search_summary" in names
    assert "echome_project_preflight" in names
    assert "echome_reflect_prepare" in names
    assert "echome_reflect_submit" in names
    assert "echome_sleep_candidates" in names


def test_unconfigured_legacy_profile_remains_full(monkeypatch) -> None:
    monkeypatch.delenv("ECHOME_MCP_PROFILE", raising=False)

    names = {tool.name for tool in asyncio.run(server_module.list_tools())}

    assert "echome_search_summary" in names
    assert "echome_sleep_candidates" in names


def test_capability_guide_only_recommends_available_core_tools(monkeypatch) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "core")

    payload = capabilities_payload()
    advertised = {entry["tool"] for entries in payload["tool_groups"].values() for entry in entries}

    assert payload["profile"] == "core"
    assert advertised <= set(payload["available_tools"])
    assert "echome_search_summary" not in advertised
    assert payload["default_retrieval_workflow"][0]["tool"] == "echome_context"


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
                "policy_effect": "helpful",
                "idempotency_key": "task-1",
            },
        )
    )

    assert result.isError is False
    assert captured["outcome"] == "success"
    assert captured["policy_effect"] == "helpful"
    assert captured["reported_by"] == "ai"


def test_runtime_health_can_include_policy_readiness(monkeypatch) -> None:
    captured: dict = {}

    async def fake_health(**kwargs) -> str:
        captured.update(kwargs)
        return json.dumps({"status": "ok"})

    monkeypatch.setattr(server_module, "echome_runtime_health", fake_health)
    result = asyncio.run(
        server_module.call_tool(
            "echome_runtime_health",
            {
                "include_policy_readiness": True,
                "project_id": "qzhqzh/EchoMe",
                "window_days": 45,
            },
        )
    )

    assert result.isError is False
    assert captured == {
        "include_policy_readiness": True,
        "project_id": "qzhqzh/EchoMe",
        "window_days": 45,
    }


def test_runtime_health_readiness_failure_is_non_fatal(monkeypatch) -> None:
    class FakeClient:
        cache_enabled = False

        async def runtime_health(self) -> dict:
            return {"status": "ok"}

        async def context_policy_readiness(self, **_kwargs) -> dict:
            raise RuntimeError("readiness unavailable")

    monkeypatch.setattr(runtime_module, "MCPHubClient", FakeClient)
    payload = json.loads(
        asyncio.run(runtime_module.echome_runtime_health(include_policy_readiness=True))
    )

    assert payload["status"] == "ok"
    assert payload["context_policy_readiness"]["status"] == "unavailable"
    assert payload["context_policy_readiness"]["auto_enforce"] is False
