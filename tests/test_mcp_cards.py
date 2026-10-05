"""Card tools expose reusable memories without allowing stale or broad AI edits."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from echome_mcp import hub_client
from echome_mcp import server as server_module
from echome_mcp.tools import cards

CARD_ID = "12345678-1234-1234-1234-123456789abc"
REVISION = "2026-10-05T10:00:00+00:00"


def _card(**overrides):
    item = {
        "id": CARD_ID,
        "title": "功能展示",
        "content": "适用时机：Web 改动后\n执行习惯：给出 https://example.test:3000/preview\n不要做：不要给未经验证的网址\n\n## 案例\n保留详细说明。",
        "tags": ["card:habit"],
        "status": "active",
        "scope": {"global": True, "projects": [], "exclude_projects": []},
        "updated_at": REVISION,
    }
    return item | overrides


def test_core_exposes_separate_read_and_write_cards(monkeypatch):
    monkeypatch.setenv("ECHOME_MCP_PROFILE", "core")
    tools = {tool.name: tool for tool in asyncio.run(server_module.list_tools())}
    assert tools["echome_card_read"].annotations.readOnlyHint is True
    assert tools["echome_card_write"].annotations.readOnlyHint is False


@pytest.mark.asyncio
async def test_mcp_dispatches_card_read_and_write(monkeypatch):
    read = AsyncMock(return_value=json.dumps({"categories": {"habit": {"items": []}}}))
    write = AsyncMock(return_value=json.dumps({"status": "created", "id": CARD_ID}))
    monkeypatch.setattr(server_module, "echome_card_read", read)
    monkeypatch.setattr(server_module, "echome_card_write", write)

    listed = await server_module.call_tool("echome_card_read", {"action": "list", "kind": "habit"})
    created = await server_module.call_tool(
        "echome_card_write",
        {
            "action": "create",
            "kind": "habit",
            "basis": "用户明确要求",
            "title": "预览",
            "fields": {},
        },
    )
    assert (
        listed.isError is False and listed.structuredContent["categories"]["habit"]["items"] == []
    )
    assert created.isError is False and created.structuredContent["status"] == "created"
    read.assert_awaited_once()
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_hub_client_edit_requires_conditional_endpoint(monkeypatch):
    paths = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": CARD_ID}

    class HTTPClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def patch(self, path, json):
            paths.append((path, json))
            return Response()

    monkeypatch.setattr(
        hub_client, "_load_config", lambda: {"hub_url": "http://test", "token": "test"}
    )
    monkeypatch.setattr(hub_client.httpx, "AsyncClient", lambda **kwargs: HTTPClient())
    payload = {"content": "执行习惯：先预览", "expected_updated_at": REVISION}
    await hub_client.MCPHubClient().patch_memory(CARD_ID, payload)
    assert paths == [(f"/api/v1/memories/{CARD_ID}/conditional", payload)]


@pytest.mark.asyncio
async def test_read_lists_compact_cards_and_gets_full_record(monkeypatch):
    class Client:
        async def list_cards(self, tag, status=None, query=None, limit=20, offset=0, project=None):
            assert (tag, status, query, project) == ("card:habit", None, "preview", "EchoMe")
            return {"total": 1, "items": [_card()]}

        async def get_memory(self, memory_id):
            assert memory_id == CARD_ID
            return _card()

    monkeypatch.setattr(cards, "MCPHubClient", Client)
    listing = json.loads(
        await cards.echome_card_read("list", "habit", query="preview", project="EchoMe")
    )
    summary = listing["categories"]["habit"]["items"][0]
    assert summary["fields"]["do"] == "给出 https://example.test:3000/preview"
    assert "content" not in summary
    detail = json.loads(await cards.echome_card_read("get", memory_id=CARD_ID))
    assert detail["card"]["content"].endswith("保留详细说明。")
    assert detail["card"]["updated_at"] == REVISION


@pytest.mark.asyncio
async def test_create_uses_review_state_and_existing_project(monkeypatch):
    calls = []

    class Client:
        async def list_cards(self, tag, status=None, query=None, limit=20, offset=0, project=None):
            calls.append(("list", status))
            return {"total": 0, "items": []}

        async def get_project(self, project):
            assert project == "EchoMe"
            return {"id": "qzhqzh/EchoMe"}

        async def create_memory(self, payload):
            calls.append(("create", payload))
            return {"id": CARD_ID}

    monkeypatch.setattr(cards, "MCPHubClient", Client)
    response = json.loads(
        await cards.echome_card_write(
            "create",
            "skill",
            "本次 Blender 建模得到可复现结果",
            "Blender 模型迭代",
            {
                "when": "建模后需要优化",
                "do": "先分析结果\n再调整模型",
                "avoid": "不要盲目重做",
                "verify": "比较预览结果",
            },
            project="EchoMe",
        )
    )
    assert response["review_status"] == "ai_review"
    payload = calls[-1][1]
    assert payload["status"] == "ai_review" and payload["source"] == "ai_suggested"
    assert payload["tags"] == ["card:skill"]
    assert payload["scope"]["projects"] == ["qzhqzh/EchoMe"]
    assert "操作步骤：1. 先分析结果；2. 再调整模型" in payload["content"]
    assert "不要做：不要盲目重做" in payload["content"]
    assert "建卡依据：本次 Blender 建模得到可复现结果" in payload["content"]


@pytest.mark.asyncio
async def test_knowledge_requires_source_and_skill_limits_steps():
    with pytest.raises(ValueError, match="evidence"):
        await cards.echome_card_write(
            "create", "knowledge", "用户提到", "WG 分层设计",
            {"claim": "救援层独立", "applies_when": "多节点网络"},
        )
    with pytest.raises(ValueError, match="at most 6 steps"):
        await cards.echome_card_write(
            "create", "skill", "实测", "过长流程",
            {"when": "执行时", "do": "\n".join(f"步骤 {i}" for i in range(7)), "verify": "检查结果"},
        )


@pytest.mark.asyncio
async def test_duplicate_title_reuses_existing_card(monkeypatch):
    class Client:
        async def list_cards(self, *args, **kwargs):
            return {"total": 1, "items": [_card(title="功能 展示", status="ai_review")]}

        async def create_memory(self, payload):
            raise AssertionError("duplicate must not be created")

    monkeypatch.setattr(cards, "MCPHubClient", Client)
    response = json.loads(
        await cards.echome_card_write(
            "create",
            "habit",
            "用户明确要求",
            "功能展示",
            {"when": "Web 修改后", "do": "给预览"},
        )
    )
    assert response["status"] == "already_exists"
    assert response["id"] == CARD_ID


@pytest.mark.asyncio
async def test_same_title_can_be_scoped_to_a_different_project(monkeypatch):
    created = []

    class Client:
        async def get_project(self, project):
            return {"id": "project-b"}

        async def list_cards(self, *args, **kwargs):
            return {
                "total": 1,
                "items": [
                    _card(
                        scope={"global": False, "projects": ["project-a"], "exclude_projects": []}
                    )
                ],
            }

        async def create_memory(self, payload):
            created.append(payload)
            return {"id": CARD_ID}

    monkeypatch.setattr(cards, "MCPHubClient", Client)
    result = json.loads(
        await cards.echome_card_write(
            "create",
            "habit",
            "用户要求本项目不同做法",
            "功能展示",
            {"when": "项目 B 修改后", "do": "提供项目 B 预览"},
            project="project-b",
        )
    )
    assert result["status"] == "created"
    assert created[0]["scope"]["projects"] == ["project-b"]


@pytest.mark.asyncio
async def test_edit_keeps_long_content_and_requires_current_revision(monkeypatch):
    calls = []

    class Client:
        async def get_memory(self, memory_id):
            return _card()

        async def patch_memory(self, memory_id, payload):
            calls.append((memory_id, payload))
            return _card(updated_at="2026-10-05T10:01:00+00:00")

    monkeypatch.setattr(cards, "MCPHubClient", Client)
    result = json.loads(
        await cards.echome_card_write(
            "edit",
            "habit",
            "用户补充域名优先规则",
            fields={"do": "优先给域名预览"},
            memory_id=CARD_ID,
            expected_updated_at=REVISION,
        )
    )
    assert result["status"] == "updated"
    assert calls[0][1]["expected_updated_at"] == REVISION
    assert "执行习惯：优先给域名预览" in calls[0][1]["content"]
    assert "不要做：不要给未经验证的网址" in calls[0][1]["content"]
    assert "## 案例\n保留详细说明。" in calls[0][1]["content"]

    with pytest.raises(ValueError, match="changed since it was read"):
        await cards.echome_card_write(
            "edit",
            "habit",
            "用户补充",
            fields={"do": "另一条"},
            memory_id=CARD_ID,
            expected_updated_at="2026-10-04T00:00:00+00:00",
        )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_edit_cannot_change_non_card_or_archived_card(monkeypatch):
    class Client:
        async def get_memory(self, memory_id):
            return _card(tags=["card:skill"], status="archived")

        async def patch_memory(self, memory_id, payload):
            raise AssertionError("unrelated memory must not be patched")

    monkeypatch.setattr(cards, "MCPHubClient", Client)
    with pytest.raises(ValueError, match="not a card"):
        await cards.echome_card_write(
            "edit",
            "habit",
            "依据",
            fields={"do": "新规则"},
            memory_id=CARD_ID,
            expected_updated_at=REVISION,
        )
