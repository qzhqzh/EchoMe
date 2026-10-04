"""The MCP scenario surface uses explicit selectors and fixed Hub endpoints."""

import asyncio
import json

from echome_mcp import server as server_module
from echome_mcp.tools import scenario as scenario_tools


def test_core_advertises_scenario_lifecycle(monkeypatch) -> None:
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "core")
    tools = {item.name: item for item in asyncio.run(server_module.list_tools())}
    assert {
        "echome_scene_read",
        "echome_scene_write",
        "echome_scenario_resolve",
        "echome_scenario_catalog",
        "echome_scenario_item",
        "echome_scenario_run",
    } <= tools.keys()
    assert tools["echome_scenario_resolve"].annotations.readOnlyHint is True
    assert tools["echome_scene_read"].annotations.readOnlyHint is True
    assert tools["echome_scene_write"].annotations.readOnlyHint is False
    assert tools["echome_scenario_run"].annotations.readOnlyHint is False


def test_resolve_and_claim_call_selected_endpoints(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeClient:
        async def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"decision": "ready_for_manual_checks"}

    monkeypatch.setattr(scenario_tools, "MCPHubClient", FakeClient)
    resolved = asyncio.run(
        scenario_tools.echome_scenario_resolve("host-check", {"target": "host-a"}, {"os": "linux"})
    )
    assert json.loads(resolved)["decision"] == "ready_for_manual_checks"
    asyncio.run(
        scenario_tools.echome_scenario_run(
            "claim",
            "12345678-1234-1234-1234-123456789abc",
            data={"idempotency_key": "check-1"},
        )
    )
    assert calls == [
        (
            "POST",
            "/resolve",
            {
                "selector": "host-check",
                "parameters": {"target": "host-a"},
                "environment": {"os": "linux"},
            },
            None,
        ),
        (
            "POST",
            "/items/12345678-1234-1234-1234-123456789abc/claim",
            {"idempotency_key": "check-1"},
            None,
        ),
    ]


def test_mcp_catalog_rejects_path_traversal() -> None:
    try:
        asyncio.run(scenario_tools.echome_scenario_catalog("get", "../other"))
    except ValueError as exc:
        assert "Invalid scenario identifier" in str(exc)
    else:
        raise AssertionError("path traversal must be rejected")


def test_mcp_item_bind_uses_explicit_endpoint(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeClient:
        async def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"item": {"scenario_slug": "host-check"}}

    monkeypatch.setattr(scenario_tools, "MCPHubClient", FakeClient)
    payload = {"scenario_slug": "host-check", "expected_revision": 3, "reason": "Validated"}
    result = asyncio.run(scenario_tools.echome_scenario_item("bind", "item-id", payload))
    assert json.loads(result)["item"]["scenario_slug"] == "host-check"
    assert calls == [("POST", "/items/item-id/bind", payload, None)]


def test_mcp_item_list_passes_case_search(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeClient:
        async def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"items": []}

    monkeypatch.setattr(scenario_tools, "MCPHubClient", FakeClient)
    asyncio.run(scenario_tools.echome_scenario_item("list", data={"query": "家庭网络"}))
    assert calls == [("GET", "/items", None, {"query": "家庭网络"})]


def test_other_ai_can_read_add_correct_and_inspect_scene_history(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeClient:
        async def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"entries": [{"key": "F001", "revision": 2}]}

    monkeypatch.setattr(scenario_tools, "MCPHubClient", FakeClient)
    read = asyncio.run(scenario_tools.echome_scene_read("get", "家庭网络"))
    assert json.loads(read)["entries"][0]["key"] == "F001"
    addition = {
        "category": "fact",
        "content": "Dated fact",
        "source_ref": "case://1",
        "evidence_at": "2026-10-04T15:17:00+08:00",
    }
    asyncio.run(scenario_tools.echome_scene_write("add", "家庭网络", data=addition))
    batch = {"entries": [addition]}
    asyncio.run(scenario_tools.echome_scene_write("add_batch", "家庭网络", data=batch))
    correction = {
        "expected_revision": 2,
        "reason": "New evidence",
        "source_ref": "case://2",
        "content": "Corrected dated fact",
        "evidence_at": "2026-10-04T16:00:00+08:00",
    }
    asyncio.run(scenario_tools.echome_scene_write("correct", "家庭网络", "entry-1", correction))
    asyncio.run(scenario_tools.echome_scene_read("history", "家庭网络", "entry-1"))
    assert calls == [
        (
            "GET",
            "/knowledge/%E5%AE%B6%E5%BA%AD%E7%BD%91%E7%BB%9C",
            None,
            {"include_archived": False},
        ),
        ("POST", "/knowledge/%E5%AE%B6%E5%BA%AD%E7%BD%91%E7%BB%9C/entries", addition, None),
        ("POST", "/knowledge/%E5%AE%B6%E5%BA%AD%E7%BD%91%E7%BB%9C/entries/batch", batch, None),
        (
            "PATCH",
            "/knowledge/%E5%AE%B6%E5%BA%AD%E7%BD%91%E7%BB%9C/entries/entry-1",
            correction,
            None,
        ),
        (
            "GET",
            "/knowledge/%E5%AE%B6%E5%BA%AD%E7%BD%91%E7%BB%9C/entries/entry-1/history",
            None,
            None,
        ),
    ]
