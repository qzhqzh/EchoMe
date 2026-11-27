"""Reading budgets must preserve discovery, caution visibility and exact expansion."""

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from echome_mcp import server
from echome_mcp.tools import knowledge, scenario
from echome_mcp.tools.read_views import knowledge_view, scene_view


def scene_fixture():
    entries = [
        {
            "id": str(uuid4()),
            "key": f"F{i:03d}",
            "category": "fact",
            "status": "active",
            "revision": 2,
            "source_ref": "case://dated-evidence",
            "evidence_at": "2026-10-26T00:00:00Z",
            "content": "条件：保持独立救援连接。" + "完整事实。" * 100,
            "validations": [],
        }
        for i in range(12)
    ]
    entries[-2].update(category="caution", content="禁止关闭救援连接。")
    entries[-1].update(status="needs_review")
    return {
        "scene": {"slug": "network", "status": "active"},
        "entries": entries,
        "counts": {"fact": 11, "caution": 1},
        "markdown": "duplicate long text" * 1000,
        "warnings": ["Do not equate historical observations with current facts."],
    }


def record_fixture():
    record_id, source_id = str(uuid4()), str(uuid4())
    evidence = {
        "source_id": source_id,
        "source_revision": 4,
        "locator": "case #5",
        "role": "refutes",
        "quote": "反例" * 1000,
    }
    return {
        "id": record_id,
        "kind": "relation",
        "revision": 2,
        "current_revision": 3,
        "status": "active",
        "current_status": "archived",
        "review_state": "historical",
        "warnings": ["Historical relation; current revision is archived."],
        "reusable": False,
        "data": {
            "statement_md": "仅适用于已确认配置的网络。" * 100,
            "qualifiers": {"never": "Do not remove the rescue path.", "network": "home"},
            "perspective": "personal",
            "valid_to": "2026-10-26T00:00:00Z",
            "evidence": [evidence],
        },
        "evidence_checks": [{**evidence, "verification_state": "mismatch"}],
    }


def test_scene_pagination_does_not_hide_cautions_and_expands_exact_entry(monkeypatch):
    raw = scene_fixture()
    original = deepcopy(raw)

    class Client:
        async def scenario_request(self, *args, **kwargs):
            return raw

    monkeypatch.setattr(scenario, "MCPHubClient", Client)
    first = json.loads(
        asyncio.run(scenario.echome_scene_read("get", "network", view="compact", limit=4))
    )
    assert "markdown" not in first
    assert first["warnings"] == raw["warnings"]
    assert first["next_offset"] == 4
    assert len(first["safety_refs"]) == 2  # Both are beyond the first page.
    assert first["caution_count"] == 1
    assert first["needs_review_count"] == 1
    assert first["entries"][0]["needs_expansion"]
    assert "content" not in first["entries"][0]
    ids = []
    offset = 0
    while offset is not None:
        page = json.loads(
            asyncio.run(
                scenario.echome_scene_read("get", "network", view="compact", offset=offset, limit=4)
            )
        )
        ids.extend(entry["id"] for entry in page["entries"])
        offset = page["next_offset"]
    assert ids == [entry["id"] for entry in raw["entries"]]
    args = first["entries"][0]["read"]["arguments"]
    expanded = json.loads(asyncio.run(scenario.echome_scene_read(**args)))
    assert expanded["entry"] == raw["entries"][0]
    assert expanded["safety_refs"] == first["safety_refs"]
    assert (
        json.loads(asyncio.run(scenario.echome_scene_read("get", "network", view="full")))
        == original
    )
    assert raw == original


def test_knowledge_scope_evidence_and_current_warnings_survive_preview(monkeypatch):
    raw = record_fixture()
    original = deepcopy(raw)
    calls = []

    class Client:
        async def knowledge_request(self, *args, **kwargs):
            calls.append((args, kwargs))
            return raw

    monkeypatch.setattr(knowledge, "MCPHubClient", Client)
    compact = json.loads(
        asyncio.run(knowledge.echome_knowledge_read("get", raw["id"], view="compact"))
    )
    assert compact["data"]["qualifiers"] == raw["data"]["qualifiers"]
    assert compact["data"]["perspective"] == "personal"
    assert compact["data"]["valid_to"] == raw["data"]["valid_to"]
    assert compact["current_revision"] == 3
    assert compact["warnings"] == raw["warnings"]
    assert compact["evidence_checks"][0]["verification_state"] == "mismatch"
    assert compact["data"]["evidence"][0]["role"] == "refutes"
    assert "quote" not in compact["data"]["evidence"][0]
    assert "data.evidence.0.quote" in compact["omitted_fields"]
    assert "statement_md" not in compact["data"]
    assert compact["needs_expansion"]
    expanded = json.loads(
        asyncio.run(knowledge.echome_knowledge_read(**compact["read"]["arguments"]))
    )
    assert expanded == original
    assert calls[-1][0][3] == {"revision": 2}
    assert raw == original


def test_context_pagination_preserves_hub_limits_and_alerts():
    record = record_fixture()
    root = {"id": str(uuid4()), "data": {"title": "Root"}, "revision": 1}
    raw = {
        "records": [root, record],
        "pinned_versions": [record],
        "truncated": True,
        "omitted_fields": [{"record_id": record["id"], "field": "data.statement_md"}],
        "continuation": "/knowledge/records?linked_to=root",
    }
    first = knowledge_view(raw, "context", {"limit": 1})
    assert first["total"] == 3 and first["next_offset"] == 1
    assert first["warning_refs"][0]["warnings"] == record["warnings"]
    assert first["truncated"] and not first["content_complete"]
    assert first["omitted_fields"] == raw["omitted_fields"]
    assert first["continuation"] == raw["continuation"]
    last = knowledge_view(raw, "context", {"offset": 2, "limit": 1})
    assert last["complete"] and last["pinned_versions"][0]["revision"] == 2
    assert last["records"] == []


def test_schema_history_and_http_errors_keep_original_contract(monkeypatch):
    raw = {"items": [{"data": {"body_md": "full history" * 1000}}]}

    class Client:
        async def knowledge_request(self, *args, **kwargs):
            return raw

    monkeypatch.setattr(knowledge, "MCPHubClient", Client)
    for action in ("schema", "history"):
        assert json.loads(asyncio.run(knowledge.echome_knowledge_read(action, str(uuid4())))) == raw

    class FailingClient:
        async def scenario_request(self, *args, **kwargs):
            response = httpx.Response(
                403, json={"detail": "Forbidden"}, request=httpx.Request("GET", "http://hub")
            )
            raise httpx.HTTPStatusError("Forbidden", request=response.request, response=response)

    monkeypatch.setattr(scenario, "MCPHubClient", FailingClient)
    error = json.loads(asyncio.run(scenario.echome_scene_read("get", "network")))
    assert error["error"] == {
        "code": "SCENARIO_REQUEST_FAILED",
        "status": 403,
        "message": "Forbidden",
    }


def test_scene_list_paginates_upstream_and_missing_entry_is_not_full_scene(monkeypatch):
    calls = []

    class Client:
        async def scenario_request(self, method, path, data=None, params=None):
            calls.append(params)
            if path == "/knowledge":
                return {"total": 9, "items": [{"slug": "network", "summary": "s" * 500}]}
            return scene_fixture()

    monkeypatch.setattr(scenario, "MCPHubClient", Client)
    listed = json.loads(
        asyncio.run(scenario.echome_scene_read("list", view="compact", limit=1, offset=3))
    )
    assert listed["next_offset"] == 4
    assert calls[0]["offset"] == 3 and calls[0]["limit"] == 1
    assert listed["items"][0]["summary_chars"] == 500
    error = json.loads(
        asyncio.run(
            scenario.echome_scene_read("get", "network", entry_id=str(uuid4()), view="compact")
        )
    )
    assert error["error"]["status"] == 404
    assert "entries" not in error


def test_mcp_read_defaults_preserve_full_views(monkeypatch):
    calls = []

    async def context(**kwargs):
        calls.append(kwargs)
        return "{}"

    monkeypatch.setattr(server, "echome_context", context)
    asyncio.run(server.call_tool("echome_context", {"task": "Check memory"}))
    asyncio.run(server.call_tool("echome_context", {"task": "Check memory", "output_mode": "full"}))
    assert calls[0]["output_mode"] == "full"
    assert calls[1]["output_mode"] == "full"
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert tools["echome_context"].inputSchema["properties"]["output_mode"]["default"] == "full"
    assert tools["echome_scene_read"].inputSchema["properties"]["view"]["default"] == "full"
    assert tools["echome_knowledge_read"].inputSchema["properties"]["view"]["default"] == "full"


def test_existing_scene_and_knowledge_reads_keep_full_responses(monkeypatch):
    scene = scene_fixture()
    scene_list = {"total": 50, "items": [{"slug": "network", "summary": "s" * 500}]}
    record = record_fixture()
    scene_calls = []
    knowledge_calls = []

    class SceneClient:
        async def scenario_request(self, method, path, data=None, params=None):
            scene_calls.append((method, path, data, params))
            return scene_list if path == "/knowledge" else scene

    class KnowledgeClient:
        async def knowledge_request(self, method, path, data=None, params=None):
            knowledge_calls.append((method, path, data, params))
            return record

    monkeypatch.setattr(scenario, "MCPHubClient", SceneClient)
    monkeypatch.setattr(knowledge, "MCPHubClient", KnowledgeClient)
    assert json.loads(asyncio.run(scenario.echome_scene_read("get", "network"))) == scene
    # Before compact views, entry_id had no effect on a get request.
    assert json.loads(
        asyncio.run(scenario.echome_scene_read("get", "network", entry_id=str(uuid4())))
    ) == scene
    assert json.loads(asyncio.run(scenario.echome_scene_read("list"))) == scene_list
    assert scene_calls[-1][3] == {"query": None, "include_archived": False}
    assert json.loads(asyncio.run(knowledge.echome_knowledge_read("get", record["id"]))) == record
    data = {"offset": 3, "limit": 20}
    assert json.loads(
        asyncio.run(knowledge.echome_knowledge_read("context", record["id"], data))
    ) == record
    assert knowledge_calls[-1][3] == data


def test_mcp_dispatch_keeps_default_full_without_implicit_scene_pagination(monkeypatch):
    scene_calls = []
    knowledge_calls = []

    async def scene_read(**kwargs):
        scene_calls.append(kwargs)
        return "{}"

    async def knowledge_read(**kwargs):
        knowledge_calls.append(kwargs)
        return "{}"

    monkeypatch.setattr(server, "echome_scene_read", scene_read)
    monkeypatch.setattr(server, "echome_knowledge_read", knowledge_read)
    asyncio.run(server.call_tool("echome_scene_read", {"action": "list"}))
    asyncio.run(server.call_tool("echome_knowledge_read", {"action": "list"}))
    assert scene_calls[0]["view"] == "full"
    assert scene_calls[0]["offset"] is None and scene_calls[0]["limit"] is None
    assert knowledge_calls[0]["view"] == "full"


@pytest.mark.parametrize(
    "params", [{"offset": -1}, {"limit": 0}, {"limit": True}, {"view": "unknown"}]
)
def test_invalid_read_options_fail_before_network(params):
    with pytest.raises(ValueError):
        asyncio.run(scenario.echome_scene_read("get", "network", **params))


def test_short_complete_records_do_not_grow_or_require_another_read():
    raw = {
        "id": str(uuid4()),
        "kind": "entity",
        "revision": 1,
        "data": {"name": "规则分流", "summary": "按已确认的规则选择路径。" * 20},
        "warnings": [],
    }
    assert knowledge_view(raw, "get", {}) == raw
    listing = {"items": [raw], "total": 1, "complete": True, "next_offset": None}
    assert knowledge_view(listing, "query", {}) == listing


def test_discovery_hints_expand_exact_records_online_and_in_cache(monkeypatch, tmp_path):
    from echome_mcp import runtime

    scene_id, record_id = str(uuid4()), str(uuid4())
    refs = [
        {
            "id": record_id,
            "source": "knowledge",
            "kind": "entity",
            "read": {
                "tool": "echome_knowledge_read",
                "arguments": {"action": "get", "record_id": record_id, "data": {"revision": 3}},
            },
        },
        {
            "id": scene_id,
            "source": "scene",
            "kind": "scene_entry",
            "read": {
                "tool": "echome_scene_read",
                "arguments": {"action": "get", "selector": "network"},
            },
        },
    ]
    fail = False

    class Client:
        cache_namespace = "test-user-only"
        cache_enabled = True

        async def unified_context(self, data):
            if fail:
                raise httpx.ConnectError("Offline")
            return {"knowledge_refs": deepcopy(refs), "runtime": {}}

    monkeypatch.setattr(runtime, "MCPHubClient", Client)
    monkeypatch.setenv("ECHOME_CONTEXT_CACHE_DIR", str(tmp_path / "cache"))
    online = json.loads(asyncio.run(runtime.echome_context("Inspect network", mode="personal")))
    fail = True
    cached = json.loads(asyncio.run(runtime.echome_context("Inspect network", mode="personal")))
    for output in (online, cached):
        arguments = output["knowledge_refs"][0]["read"]["arguments"]
        assert arguments["view"] == "full" and arguments["data"]["revision"] == 3
        scene_arguments = output["knowledge_refs"][1]["read"]["arguments"]
        assert scene_arguments["entry_id"] == scene_id and scene_arguments["view"] == "compact"
    assert cached["runtime"]["fallback"] == "last_known_good"


def test_exact_read_hints_never_displace_context_at_its_explicit_budget(monkeypatch):
    from echome_mcp import runtime
    from echome_mcp.context_output import serialize_context

    record_id = str(uuid4())
    raw = {
        "knowledge_refs": [
            {
                "id": record_id,
                "kind": "entity",
                "read": {
                    "tool": "echome_knowledge_read",
                    "arguments": {"action": "get", "record_id": record_id},
                },
            }
        ],
        "personal_context": "Full applicable conditions and prohibitions." * 50,
    }
    cap = len(serialize_context(deepcopy(raw), compact=True, limit=6000).encode("utf-8"))

    class Client:
        cache_namespace = "budget-test"
        cache_enabled = False

        async def unified_context(self, data):
            return deepcopy(raw)

    monkeypatch.setattr(runtime, "MCPHubClient", Client)
    encoded = asyncio.run(
        runtime.echome_context(
            "Known task", mode="personal", output_mode="compact", max_output_tokens=cap
        )
    )
    output = json.loads(encoded)
    assert "error" not in output
    assert output["personal_context"] == raw["personal_context"]
    assert output["knowledge_refs"] == raw["knowledge_refs"]
    assert len(encoded.encode("utf-8")) <= cap
