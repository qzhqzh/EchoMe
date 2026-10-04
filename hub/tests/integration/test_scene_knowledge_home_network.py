"""A real recorded household-network case exercises the text-first scene workflow.

Historical evidence is imported only into this disposable integration schema. The
test never contacts the household network or claims its diagnostic SOP is validated.
"""

import uuid

import httpx
import pytest

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User

SOURCE = "case-study:2026-10-04-home-network-v0.3"
EVIDENCE_AT = "2026-10-04T15:17:00+08:00"


async def _add(api, category: str, content: str, *, dated: bool = False):
    result = await api.post(
        "scenarios/knowledge/home-network/entries",
        json={
            "category": category,
            "content": content,
            "source_ref": SOURCE,
            "evidence_at": EVIDENCE_AT if dated else None,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()["entry"]


@pytest.mark.asyncio
async def test_home_network_knowledge_is_atomic_correctable_and_has_zero_sops(api) -> None:
    created = await api.post(
        "scenarios/knowledge",
        json={
            "slug": "home-network",
            "title": "柴泊新家园家庭网络",
            "summary": "家庭网络资料与下载慢排查；历史测量不代表当前状态。",
            "aliases": ["家庭网络", "柴泊新家园网络"],
        },
    )
    assert created.status_code == 201, created.text

    facts = [
        "电信网关 HN8145V 的管理地址为 192.168.1.1。",
        "TP-Link TL-XDR3010 的 WAN 地址为 192.168.1.10。",
        "TP-Link 家庭 LAN 网段为 192.168.0.0/24。",
        "电脑通过 WLAN 2 连接 TP-Link 的 5 GHz Wi-Fi，使用 802.11ac、信道 40。",
        "2026-10-04 检查时，TP-Link 的 IPv6 状态为关闭。",
        "2026-10-04 检查时，TP-Link 未对这台电脑配置上下行限速。",
    ]
    imported = await api.post(
        "scenarios/knowledge/home-network/entries/batch",
        json={
            "entries": [
                {
                    "category": "fact",
                    "content": content,
                    "source_ref": SOURCE,
                    "evidence_at": EVIDENCE_AT,
                }
                for content in facts
            ]
        },
    )
    assert imported.status_code == 201, imported.text
    assert [item["key"] for item in imported.json()["entries"]] == [
        f"F{number:03d}" for number in range(1, 7)
    ]
    first = imported.json()["entries"][0]
    rejected_batch = await api.post(
        "scenarios/knowledge/home-network/entries/batch",
        json={
            "entries": [
                {
                    "category": "fact",
                    "content": "A new fact that must roll back.",
                    "source_ref": SOURCE,
                    "evidence_at": EVIDENCE_AT,
                },
                {
                    "category": "fact",
                    "content": facts[0],
                    "source_ref": SOURCE,
                    "evidence_at": EVIDENCE_AT,
                },
            ]
        },
    )
    assert rejected_batch.status_code == 409
    for content in (
        "四轮 Wi-Fi 下载测速为 193.53、250.65、224.81、288.58 Mbps。",
        "同四轮上传测速范围为 51.70–53.15 Mbps。",
        "一次低负载窗口中，到家庭路由器的探测 600/600 成功，P95 为 3 ms；仅该窗口满足 Q04。",
        "一次短时下载负载中，本机到路由器的 P95 从 3 ms 升至 63 ms；下载阶段仅 16 个样本，未满足正式 60 秒验收。",
    ):
        await _add(api, "observation", content, dated=True)
    for content in (
        "测速时核对实际流量出口；FlClash TUN 开启不等于流量一定经过外部代理。",
        "WireGuard 的 10.0.0.x 是辅助网络，不是家庭主路由地址。",
        "Wi-Fi 协商速率不能当作实际下载吞吐。",
        "这份资料没有授权修改网络配置；执行变更前须单独确认。",
    ):
        await _add(api, "caution", content)
    work = await _add(
        api,
        "work",
        "下载偏慢与负载延迟升高的根因未知。下一步做同机千兆有线对照；等待电脑接入 TP-Link LAN 口。",
    )

    by_alias = await api.get("scenarios/knowledge/家庭网络")
    assert by_alias.status_code == 200, by_alias.text
    assert by_alias.json()["counts"] == {
        "fact": 6,
        "observation": 4,
        "sop": 0,
        "caution": 4,
        "work": 1,
    }
    markdown = by_alias.json()["markdown"]
    assert "F001" in markdown and "F006" in markdown
    assert "## 已验证 SOP（0 条）\n暂无。" in markdown
    assert "根因未知" in markdown
    assert work["key"] == "T001"

    # An AI cannot silently turn a one-off investigation step into a formal SOP.
    direct_sop = await api.post(
        "scenarios/knowledge/home-network/entries",
        json={
            "category": "sop",
            "content": "先测速",
            "source_ref": SOURCE,
        },
    )
    assert direct_sop.status_code == 422
    unvalidated = await api.post(
        "scenarios/knowledge/home-network/sops",
        json={
            "content": (
                "## 目的\n排查这处家庭网络的下载速率变化。\n"
                "## 适用条件\n仅适用于已确认设备与当前出口路径。\n"
                "## 工具\n记录 PowerShell 和测速工具的实际版本。\n"
                "## 步骤\n1. 核对接口、网关和出口。\n2. 固定节点保存原始测速结果。\n"
                "## 验收\n比较路径、速率及负载延迟。\n"
                "## 验证依据\n目前只有一次历史测量，尚不能证明流程可复用。"
            ),
            "source_ref": SOURCE,
            "validations": [
                {
                    "executed_at": EVIDENCE_AT,
                    "session_id": "only-one",
                    "conditions": "Historical Wi-Fi test only",
                    "observed_result": "One dated measurement, no repeat validation",
                    "evidence_ref": SOURCE,
                    "result": "effective",
                }
            ],
        },
    )
    assert unvalidated.status_code == 422
    assert "at least 3" in unvalidated.text
    assert (await api.get("scenarios/knowledge/home-network")).json()["counts"]["sop"] == 0

    # Another AI reads the current revision, clarifies an existing fact and adds
    # one separate observation without replacing the other facts.
    corrected = await api.patch(
        f"scenarios/knowledge/home-network/entries/{first['id']}",
        json={
            "expected_revision": first["revision"],
            "content": "2026-10-04 核实时，电信网关 HN8145V 的管理地址为 192.168.1.1。",
            "reason": "限定为来源资料核实时的地址，避免把历史配置说成永远不变。",
            "source_ref": SOURCE,
            "evidence_at": EVIDENCE_AT,
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["entry"]["revision"] == 2
    stale = await api.patch(
        f"scenarios/knowledge/home-network/entries/{first['id']}",
        json={
            "expected_revision": 1,
            "status": "needs_review",
            "reason": "stale agent write",
            "source_ref": SOURCE,
        },
    )
    assert stale.status_code == 409
    history = await api.get(f"scenarios/knowledge/home-network/entries/{first['id']}/history")
    assert [change["revision"] for change in history.json()["items"]] == [1, 2]
    assert history.json()["items"][0]["snapshot"]["content"] == facts[0]
    assert (await api.get("scenarios/knowledge/home-network")).json()["counts"]["fact"] == 6

    archived = await api.patch(
        f"scenarios/knowledge/home-network/entries/{work['id']}",
        json={
            "expected_revision": work["revision"],
            "status": "archived",
            "reason": "Review-only check of archived document output",
            "source_ref": SOURCE,
        },
    )
    assert archived.status_code == 200, archived.text
    assert "T001〔已归档〕" not in (await api.get("scenarios/knowledge/home-network")).json()["markdown"]
    archived_doc = await api.get("scenarios/knowledge/home-network?include_archived=true")
    assert "T001〔已归档〕" in archived_doc.json()["markdown"]


@pytest.mark.asyncio
async def test_formal_sop_requires_repeat_evidence_and_revalidation_on_edit(api) -> None:
    created = await api.post(
        "scenarios/knowledge",
        json={
            "slug": "sop-gate-fixture",
            "title": "SOP gate fixture",
            "summary": "Synthetic admission test",
        },
    )
    assert created.status_code == 201, created.text
    content = (
        "## 目的\n在固定测试环境排查网络速度异常。\n"
        "## 适用条件\n仅用于已确认的测试主机和目标网络。\n"
        "## 工具\n记录操作系统、测速软件名称和版本，以及所用节点。\n"
        "## 步骤\n1. 核查接口和默认网关，保存原始结果。\n"
        "2. 固定节点执行测试，记录每轮时间、速率和负载延迟。\n"
        "## 验收\n能复现并解释每轮测试路径和数值。\n"
        "## 验证依据\n以下三次为此测试专用的独立模拟记录，不表示家庭网络已验证。"
    )
    validations = [
        {
            "executed_at": f"2026-10-0{day}T10:00:00+08:00",
            "session_id": session,
            "conditions": "Disposable test host, fixed fixture input",
            "observed_result": "Fixture method returned the expected classification",
            "evidence_ref": f"fixture://run-{day}",
            "result": "effective",
        }
        for day, session in ((1, "a"), (2, "b"), (3, "b"))
    ]
    same_session = [{**item, "session_id": "a"} for item in validations]
    denied = await api.post(
        "scenarios/knowledge/sop-gate-fixture/sops",
        json={
            "content": content,
            "source_ref": "fixture://sop",
            "validations": same_session,
        },
    )
    assert denied.status_code == 422
    published = await api.post(
        "scenarios/knowledge/sop-gate-fixture/sops",
        json={
            "content": content,
            "source_ref": "fixture://sop",
            "validations": validations,
        },
    )
    assert published.status_code == 201, published.text
    sop = published.json()["entry"]
    assert sop["key"] == "S001"
    invalid_edit = await api.patch(
        f"scenarios/knowledge/sop-gate-fixture/entries/{sop['id']}",
        json={
            "expected_revision": 1,
            "reason": "Change steps",
            "source_ref": "fixture://sop",
            "content": content + "\n3. 补充未经验证的步骤。",
        },
    )
    assert invalid_edit.status_code == 422
    assert (await api.get("scenarios/knowledge/sop-gate-fixture")).json()["entries"][0][
        "revision"
    ] == 1
    review = await api.patch(
        f"scenarios/knowledge/sop-gate-fixture/entries/{sop['id']}",
        json={
            "expected_revision": 1,
            "reason": "Tool version changed",
            "source_ref": "fixture://tool-change",
            "status": "needs_review",
        },
    )
    assert review.status_code == 200, review.text
    assert (await api.get("scenarios/knowledge/sop-gate-fixture")).json()["counts"]["sop"] == 0
    unverified_reactivation = await api.patch(
        f"scenarios/knowledge/sop-gate-fixture/entries/{sop['id']}",
        json={
            "expected_revision": 2,
            "reason": "Try to restore without retesting",
            "source_ref": "fixture://tool-change",
            "status": "active",
        },
    )
    assert unverified_reactivation.status_code == 422
    reused = await api.patch(
        f"scenarios/knowledge/sop-gate-fixture/entries/{sop['id']}",
        json={
            "expected_revision": 2,
            "reason": "Try to reuse old test runs",
            "source_ref": "fixture://tool-change",
            "status": "active",
            "validations": validations,
        },
    )
    assert reused.status_code == 422


@pytest.mark.asyncio
async def test_scene_knowledge_is_private_to_the_authenticated_user(api, database) -> None:
    created = await api.post(
        "scenarios/knowledge",
        json={"slug": "private-network", "title": "Private network", "aliases": ["我的网络"]},
    )
    assert created.status_code == 201, created.text
    entry = await api.post(
        "scenarios/knowledge/private-network/entries",
        json={
            "category": "fact",
            "content": "Private dated network fact.",
            "source_ref": "fixture://private",
            "evidence_at": EVIDENCE_AT,
        },
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["entry"]["id"]

    other_id = uuid.uuid4()
    async with database() as session:
        session.add(User(id=other_id, github_id=2, username="other-scene-user"))
        await session.commit()
    token, _ = create_access_token(user_id=other_id, username="other-scene-user", role="user")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://integration/api/v1/",
        headers={"Authorization": f"Bearer {token}"},
    ) as other:
        assert (await other.get("scenarios/knowledge")).json()["total"] == 0
        assert (await other.get("scenarios/knowledge/我的网络")).status_code == 404
        assert (
            await other.get(f"scenarios/knowledge/private-network/entries/{entry_id}/history")
        ).status_code == 404
        assert (
            await other.patch(
                f"scenarios/knowledge/private-network/entries/{entry_id}",
                json={
                    "expected_revision": 1,
                    "reason": "Attempt cross-user edit",
                    "source_ref": "fixture://other",
                    "status": "archived",
                },
            )
        ).status_code == 404
