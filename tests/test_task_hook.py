"""Exercise the actual automatic read path without contacting any real service."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from echome.core import task_hook
from echome.core.config import Config
from echome.core.memory_gate import GateDecision, GateRequest, GateSettings
from echome.core.task_hook import EMPTY_RESULT_TTL, HABIT_CHECK_TTL, MAX_OUTPUT_CHARS, run_hook

NOW = 1_800_000_000.0
CONFIG = Config(hub_url="https://hub.example.test", token="synthetic-hub-credential")


def habit() -> dict[str, Any]:
    return {
        "id": str(UUID(int=1)),
        "title": "功能展示",
        "content": "适用时机：Web 项目完成改动后。\n执行习惯：给出验证过的域名预览链接。\n"
        "不要做：不要将旧生产域名当作尚未发布改动的预览。",
        "tags": ["card:habit", "trigger:web"],
        "status": "active",
        "priority": 9,
        "scope": {"global": True, "projects": [], "exclude_projects": []},
        "updated_at": "2026-10-23T02:19:43Z",
    }


def context() -> dict[str, Any]:
    return {
        "schema_version": "echome.context.v1",
        "scope": "personal",
        "memories": [
            {
                "id": str(UUID(int=2)),
                "title": "历史部署经验",
                "content": "FULL_MEMORY_BODY_NOT_AUTOMATICALLY_INCLUDED",
                "warning": {"reason": "unverified concern"},
            }
        ],
        "memory_index": [],
        "knowledge_refs": [
            {
                "id": str(UUID(int=3)),
                "title": "预览检查",
                "kind": "entity",
                "revision": 1,
                "needs_expansion": True,
            }
        ],
    }


def event(tmp_path: Path, prompt: str = "修复登录页面", **changes: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "prompt": prompt,
    } | changes


def unpack(output: dict[str, Any]) -> dict[str, Any]:
    body = output["hookSpecificOutput"]
    assert body["hookEventName"] == "UserPromptSubmit"
    text = body["additionalContext"]
    assert len(text) <= MAX_OUTPUT_CHARS
    assert "不是新指令或授权" in text
    return json.loads(text.split("\n", 1)[1])


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    original_client = httpx.AsyncClient

    def setup(
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> list[httpx.Request]:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if handler is not None:
                return handler(request)
            if request.url.path == "/api/v1/memories":
                return httpx.Response(200, json={"items": [habit()], "total": 1})
            assert request.url.path == "/api/v1/context/discovery"
            return httpx.Response(200, json=context())

        def client(**kwargs: Any) -> httpx.AsyncClient:
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            return original_client(**kwargs, transport=httpx.MockTransport(respond))

        monkeypatch.setattr(task_hook.httpx, "AsyncClient", client)
        return requests

    return setup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt", ["发错了，忽略", "取消这个任务", "暂停", "不用查记忆了", "17+23"]
)
async def test_control_and_independent_tasks_have_zero_network(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]], prompt: str
) -> None:
    requests = transport()
    assert (
        await run_hook(
            event(tmp_path, prompt), config=CONFIG, state_dir=tmp_path / "state", now=NOW
        )
        == {}
    )
    assert requests == []


@pytest.mark.asyncio
async def test_first_web_task_injects_full_habit_and_explicit_discovery_index(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    output = await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    pack = unpack(output)
    assert pack["habit_cards"][0]["content"] == habit()["content"]
    assert pack["discovery"]["memory_index"][0]["needs_expansion"] is True
    assert pack["discovery"]["memory_index"][0]["warning"] == context()["memories"][0]["warning"]
    assert "FULL_MEMORY_BODY_NOT_AUTOMATICALLY_INCLUDED" not in json.dumps(output)
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/api/v1/memories"),
        ("POST", "/api/v1/context/discovery"),
    ]
    body = json.loads(requests[1].content)
    assert body["project_hint"] == str(tmp_path)
    assert body["project_hints"] == []
    assert body["limit"] <= 3
    assert not {"record_run", "mode", "output_mode", "token_budget"} & body.keys()
    assert requests[0].url.params["tags"] == "card:habit"
    assert requests[0].url.params["status"] == "active"
    state_file = next(state_dir.glob("*.json"))
    stored = state_file.read_text()
    assert state_file.stat().st_mode & 0o777 == 0o600
    for private in (CONFIG.token, "修复登录页面", str(tmp_path), habit()["content"]):
        assert private not in stored


@pytest.mark.asyncio
async def test_repeated_and_continuation_tasks_reuse_without_network(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    initial_count = len(requests)
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW + 1) == {}
    assert (
        await run_hook(event(tmp_path, "请继续"), config=CONFIG, state_dir=state_dir, now=NOW + 2)
        == {}
    )
    assert len(requests) == initial_count


@pytest.mark.asyncio
async def test_explicit_freshness_request_is_not_suppressed_by_exact_prompt_cache(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    request = event(tmp_path, "重新查询记忆中的家庭网络配置")
    assert await run_hook(request, config=CONFIG, state_dir=state_dir, now=NOW)
    assert await run_hook(request, config=CONFIG, state_dir=state_dir, now=NOW + 1)
    assert len(requests) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_second"),
    [
        ("请重新检查项目的 Git 状态", 0),
        ("重新计算文件校验值，按记忆中的部署约定执行", 0),
        ("请刷新记忆", 2),
        ("先重新检查 Git，然后重新查询记忆中的部署约定", 2),
    ],
)
async def test_refresh_bypasses_cache_only_for_memory_intent(
    tmp_path: Path,
    transport: Callable[..., list[httpx.Request]],
    prompt: str,
    expected_second: int,
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    first = await run_hook(event(tmp_path, prompt), config=CONFIG, state_dir=state_dir, now=NOW)
    assert first and len(requests) == 2
    await run_hook(event(tmp_path, prompt), config=CONFIG, state_dir=state_dir, now=NOW + 1)
    assert len(requests) == 2 + expected_second


@pytest.mark.asyncio
async def test_explicit_no_memory_precedes_project_and_refresh(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    output = await run_hook(
        event(tmp_path, "不要读取任何记忆，只重新检查项目的 Git 状态"),
        config=CONFIG,
        state_dir=tmp_path / "state",
        now=NOW,
    )
    assert output == {} and requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "model_action", "degraded", "expected_requests", "expected_model_calls"),
    [
        ("off", "retrieve", False, 0, 0),
        ("legacy", "skip", False, 2, 1),
        ("shadow", "retrieve", False, 0, 1),
        ("assist", "retrieve", False, 2, 1),
        ("assist", "skip", False, 0, 1),
        ("assist", None, True, 2, 1),
    ],
)
async def test_model_can_only_supplement_a_soft_skip_and_can_be_disabled(
    tmp_path: Path,
    transport: Callable[..., list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    model_action: str | None,
    degraded: bool,
    expected_requests: int,
    expected_model_calls: int,
) -> None:
    requests = transport()
    model_calls: list[GateRequest] = []

    async def suggestion(request: GateRequest, settings: GateSettings) -> GateDecision:
        model_calls.append(request)
        return GateDecision(
            phase="read",
            action="retrieve" if degraded else model_action,
            provider="piccolo",
            reason_code="provider_timeout" if degraded else "model_choice",
            model_action=model_action,
            latency_ms=5,
            degraded=degraded,
        )

    monkeypatch.setattr(task_hook, "suggest_hook_read", suggestion)
    state_dir = tmp_path / "state"
    await run_hook(
        event(tmp_path, "这次也按我惯用的方式提交。"),
        config=CONFIG,
        state_dir=state_dir,
        gate=GateSettings(provider="piccolo", base_url="http://127.0.0.1:18643"),
        model_mode=mode,
        now=NOW,
    )
    assert len(requests) == expected_requests
    assert len(model_calls) == expected_model_calls
    stored = next(state_dir.glob("*.json")).read_text()
    assert "这次也按我惯用的方式提交" not in stored


@pytest.mark.asyncio
async def test_model_never_overrides_an_existing_rule_read_or_explicit_refresh(
    tmp_path: Path,
    transport: Callable[..., list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport()

    async def forbidden(*args: Any, **kwargs: Any) -> GateDecision:
        pytest.fail("Rule reads and explicit refreshes must not call the model")

    monkeypatch.setattr(task_hook, "suggest_hook_read", forbidden)
    gate = GateSettings(provider="piccolo", base_url="http://127.0.0.1:18643")
    for index, text in enumerate(["修复登录页面", "请刷新记忆"]):
        await run_hook(
            event(tmp_path, text),
            config=CONFIG,
            state_dir=tmp_path / "state",
            gate=gate,
            model_mode="assist",
            now=NOW + index,
        )
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_model_observation_is_per_turn_but_attempt_count_is_cumulative(
    tmp_path: Path,
    transport: Callable[..., list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport()

    async def suggestion(request: GateRequest, settings: GateSettings) -> GateDecision:
        return GateDecision(
            phase="read",
            action="skip",
            provider="piccolo",
            reason_code="model_choice",
            model_action="skip",
            latency_ms=5,
        )

    monkeypatch.setattr(task_hook, "suggest_hook_read", suggestion)
    gate = GateSettings(provider="piccolo", base_url="http://127.0.0.1:18643")
    state_dir = tmp_path / "state"
    await run_hook(
        event(tmp_path, "这次也按我惯用的方式提交。"),
        config=CONFIG,
        state_dir=state_dir,
        gate=gate,
        model_mode="assist",
        now=NOW,
    )
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert state["model_observation"]["action"] == "skip"
    assert state["counts"]["model_attempts"] == 1
    await run_hook(
        event(tmp_path, "修复登录页面"),
        config=CONFIG,
        state_dir=state_dir,
        gate=gate,
        model_mode="assist",
        now=NOW + 1,
    )
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert "model_observation" not in state
    assert state["counts"]["model_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_choice", "model_status", "expected_hub_requests"),
    [("retrieve", 200, 2), ("skip", 200, 0), ("skip", 503, 2)],
)
async def test_online_jev_supplements_only_the_existing_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_choice: str,
    model_status: int,
    expected_hub_requests: int,
) -> None:
    actual_client = httpx.AsyncClient
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "model.example.test":
            assert request.headers["authorization"] == "Bearer synthetic-jev-token"
            assert (
                json.loads(request.content)["state"]["user_message"] == "这次也按我惯用的方式提交。"
            )
            probabilities = (
                {"retrieve": 0.9, "skip": 0.1}
                if model_choice == "retrieve"
                else {"retrieve": 0.1, "skip": 0.9}
            )
            return httpx.Response(
                model_status,
                json={
                    "answers": {
                        "action": {
                            "type": "choice",
                            "choice": model_choice,
                            "probabilities": probabilities,
                        }
                    }
                },
            )
        if request.url.path == "/api/v1/memories":
            return httpx.Response(200, json={"items": [habit()], "total": 1})
        return httpx.Response(200, json=context())

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return actual_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(task_hook.httpx, "AsyncClient", client)
    state_dir = tmp_path / "state"
    await run_hook(
        event(tmp_path, "这次也按我惯用的方式提交。"),
        config=CONFIG,
        state_dir=state_dir,
        gate=GateSettings(
            provider="jev", base_url="https://model.example.test", api_key="synthetic-jev-token"
        ),
        model_mode="assist",
        now=NOW,
    )
    assert sum(call.url.host == "model.example.test" for call in calls) == 1
    assert sum(call.url.host == "hub.example.test" for call in calls) == expected_hub_requests
    stored = next(state_dir.glob("*.json")).read_text()
    assert "synthetic-jev-token" not in stored and "我惯用的方式" not in stored


@pytest.mark.asyncio
async def test_new_task_reuses_habit_but_reads_new_discovery(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    second = unpack(
        await run_hook(
            event(tmp_path, "优化首页的样式"), config=CONFIG, state_dir=state_dir, now=NOW + 1
        )
    )
    assert "habit_cards" not in second
    assert len(requests) == 3 and requests[-1].url.path == "/api/v1/context/discovery"


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", ["account", "cwd"])
async def test_account_and_working_directory_have_separate_state(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]], dimension: str
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    other_config = (
        CONFIG.model_copy(update={"token": "second-synthetic-credential"})
        if dimension == "account"
        else CONFIG
    )
    other_cwd = tmp_path / "different-project" if dimension == "cwd" else tmp_path
    second = unpack(
        await run_hook(event(other_cwd), config=other_config, state_dir=state_dir, now=NOW + 1)
    )
    assert second["habit_cards"][0]["content"] == habit()["content"]
    assert len(requests) == 4
    assert len(list(state_dir.glob("*.json"))) == 2


@pytest.mark.asyncio
async def test_compaction_clears_delivery_state_without_reading_hub(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    assert (
        await run_hook(
            event(tmp_path, hook_event_name="SessionStart", source="compact"),
            config=CONFIG,
            state_dir=state_dir,
            now=NOW + 1,
        )
        == {}
    )
    assert len(requests) == 2
    second = unpack(
        await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW + 2)
    )
    assert "habit_cards" in second and len(requests) == 4


@pytest.mark.asyncio
async def test_hub_failure_fails_open_and_backoff_prevents_repeated_network(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport(lambda _: httpx.Response(503, text="server-secret-must-not-escape"))
    state_dir = tmp_path / "state"
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW) == {}
    initial_count = len(requests)
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW + 1) == {}
    assert len(requests) == initial_count
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert not state.get("delivered")
    assert "server-secret" not in json.dumps(state)
    assert state["last_decision"]["action"] != "delivered"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"prompt": "修改页面 password=SYNTHETIC_ONLY"},
        {"prompt": "x" * 4001},
        {"prompt": ""},
        {"prompt": 9},
        {"cwd": "relative/path"},
        {"cwd": None},
        {"session_id": "x" * 257},
        {"hook_event_name": "BeforeAnything"},
    ],
)
async def test_sensitive_and_invalid_events_do_not_make_requests(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]], change: dict[str, Any]
) -> None:
    requests = transport()
    assert (
        await run_hook(
            event(tmp_path, **change), config=CONFIG, state_dir=tmp_path / "state", now=NOW
        )
        == {}
    )
    assert requests == []


@pytest.mark.asyncio
async def test_oversized_discovery_preserves_whole_habit_without_claiming_task_delivery(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [habit()]})
        payload = context()
        payload["knowledge_refs"][0]["title"] = "冗长资料" * 3000
        return httpx.Response(200, json=payload)

    transport(respond)
    state_dir = tmp_path / "state"
    pack = unpack(await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW))
    assert pack["habit_cards"][0]["content"] == habit()["content"]
    assert "discovery" not in pack
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert not state.get("delivered")
    assert state["counts"]["discovery_dropped"] == 1


@pytest.mark.asyncio
async def test_secret_in_hub_metadata_does_not_escape_or_mark_discovery_delivered(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [habit()]})
        payload = context()
        payload["memories"][0]["title"] = "password=SYNTHETIC_ONLY"
        return httpx.Response(200, json=payload)

    transport(respond)
    state_dir = tmp_path / "state"
    output = await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    assert "SYNTHETIC_ONLY" not in json.dumps(output)
    assert unpack(output)["habit_cards"][0]["content"] == habit()["content"]
    assert not json.loads(next(state_dir.glob("*.json")).read_text()).get("delivered")


@pytest.mark.asyncio
async def test_malformed_success_response_is_not_marked_delivered(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    transport(lambda _: httpx.Response(200, json={}))
    state_dir = tmp_path / "state"
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW) == {}
    assert not json.loads(next(state_dir.glob("*.json")).read_text()).get("delivered")


@pytest.mark.asyncio
async def test_empty_valid_context_is_not_a_successful_injection(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(
            200,
            json={
                "schema_version": "echome.context.v1",
                "scope": "personal",
                "memories": [],
                "memory_index": [],
                "knowledge_refs": [],
            },
        )

    transport(respond)
    state_dir = tmp_path / "state"
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW) == {}
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert not state.get("delivered") and not state.get("counts", {}).get("delivered")


@pytest.mark.asyncio
async def test_optional_habit_shape_failure_still_delivers_discovery(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [None]})
        return httpx.Response(200, json=context())

    transport(respond)
    state_dir = tmp_path / "state"
    pack = unpack(await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW))
    assert "discovery" in pack and "habit_cards" not in pack
    assert json.loads(next(state_dir.glob("*.json")).read_text())["counts"]["habit_failure"] == 1


@pytest.mark.asyncio
async def test_context_timeout_preserves_complete_habit_and_does_not_mark_task_delivered(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [habit()]})
        raise httpx.ReadTimeout("SYNTHETIC_SERVER_SECRET", request=request)

    transport(respond)
    state_dir = tmp_path / "state"
    output = await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    assert unpack(output)["habit_cards"][0]["content"] == habit()["content"]
    assert "SYNTHETIC_SERVER_SECRET" not in json.dumps(output)
    assert not json.loads(next(state_dir.glob("*.json")).read_text()).get("delivered")


@pytest.mark.asyncio
async def test_missing_hub_credentials_have_zero_network(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    assert (
        await run_hook(
            event(tmp_path),
            config=CONFIG.model_copy(update={"token": ""}),
            state_dir=tmp_path / "state",
            now=NOW,
        )
        == {}
    )
    assert requests == []


@pytest.mark.asyncio
async def test_symlinked_state_ancestor_is_not_followed(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    link = tmp_path / "linked-parent"
    link.symlink_to(outside, target_is_directory=True)
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=link / "state", now=NOW) == {}
    assert not (outside / "state").exists()
    assert requests == []


@pytest.mark.asyncio
async def test_hardlinked_state_file_is_not_truncated(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    await run_hook(
        event(tmp_path, hook_event_name="SessionStart"), config=CONFIG, state_dir=state_dir, now=NOW
    )
    path = next(state_dir.glob("*.json"))
    other = tmp_path / "important-file"
    os.link(path, other)
    original = other.read_bytes()
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW + 1) == {}
    assert other.read_bytes() == original
    assert requests == []


def empty_context() -> dict[str, Any]:
    return {
        "schema_version": "echome.context.v1",
        "scope": "personal",
        "memories": [],
        "memory_index": [],
        "knowledge_refs": [],
    }


@pytest.mark.asyncio
async def test_exact_empty_result_is_reused_briefly_then_retried(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(200, json=empty_context())

    requests = transport(respond)
    state_dir = tmp_path / "state"
    task = event(tmp_path, "设计量子贝尔不等式实验")
    assert await run_hook(task, config=CONFIG, state_dir=state_dir, now=NOW) == {}
    assert len(requests) == 2
    assert await run_hook(task, config=CONFIG, state_dir=state_dir, now=NOW + 1) == {}
    assert len(requests) == 2
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert state["last_decision"]["reason"] == "exact_empty_result_cached"
    assert state["last_execution"]["requests"] == 0
    assert not state.get("delivered")
    await run_hook(task, config=CONFIG, state_dir=state_dir, now=NOW + EMPTY_RESULT_TTL)
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_empty_cache_does_not_merge_related_but_distinct_tasks(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(200, json=empty_context())

    requests = transport(respond)
    state_dir = tmp_path / "state"
    for index, prompt in enumerate(["配置家庭网络的 VPN 隧道", "配置家庭网络的规则分流"]):
        await run_hook(event(tmp_path, prompt), config=CONFIG, state_dir=state_dir, now=NOW + index)
    assert sum(request.url.path.endswith("discovery") for request in requests) == 2
    assert len(requests) == 3  # An empty complete habit catalog may be reused.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "重新查询记忆中的网络配置",
        "读取最新家庭网络配置",
        "读取刚刚新增的习惯卡",
        "检查习惯更新后的 Web 预览规则",
        "请按新保存的记忆修改页面",
    ],
)
async def test_explicit_freshness_bypasses_empty_and_habit_caches(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]], prompt: str
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(200, json=empty_context())

    requests = transport(respond)
    state_dir = tmp_path / "state"
    for index in range(2):
        await run_hook(event(tmp_path, prompt), config=CONFIG, state_dir=state_dir, now=NOW + index)
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_unmatched_habit_cannot_hide_when_next_task_needs_it(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    (tmp_path / "package.json").write_text('{"dependencies":{"vue":"3"}}')
    state_dir = tmp_path / "state"
    first = unpack(
        await run_hook(
            event(tmp_path, "整理我们的家庭网络架构"), config=CONFIG, state_dir=state_dir, now=NOW
        )
    )
    assert "habit_cards" not in first and "discovery" in first
    second = unpack(
        await run_hook(
            event(tmp_path, "优化手机端按钮布局"), config=CONFIG, state_dir=state_dir, now=NOW + 1
        )
    )
    assert second["habit_cards"][0]["id"] == habit()["id"]
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_empty_discovery_does_not_cache_a_failed_habit_request(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            if len(requests) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"items": [habit()], "total": 1})
        return httpx.Response(200, json=empty_context())

    requests = transport(respond)
    state_dir = tmp_path / "state"
    assert await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW) == {}
    output = await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW + 1)
    assert unpack(output)["habit_cards"][0]["id"] == habit()["id"]
    assert len(requests) == 3  # Retry habits; the known-empty discovery stays cached.


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [None, 101])
async def test_unknown_or_incomplete_habit_catalog_is_not_cached(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]], total: int | None
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [habit()], "total": total})
        return httpx.Response(200, json=context())

    requests = transport(respond)
    state_dir = tmp_path / "state"
    for index, prompt in enumerate(["修改登录页面", "优化首页样式"]):
        await run_hook(event(tmp_path, prompt), config=CONFIG, state_dir=state_dir, now=NOW + index)
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_habit_cache_expiry_checks_new_cards_without_reinjecting_known_versions(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    new_card = habit() | {
        "id": str(UUID(int=20)),
        "title": "移动端验收",
        "content": "适用时机：Web 项目完成改动后。\n执行习惯：检查手机显示。",
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            cards = [habit()] if len(requests) == 1 else [habit(), new_card]
            return httpx.Response(200, json={"items": cards, "total": len(cards)})
        return httpx.Response(200, json=context())

    requests = transport(respond)
    state_dir = tmp_path / "state"
    await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    output = await run_hook(
        event(tmp_path, "优化首页的样式"),
        config=CONFIG,
        state_dir=state_dir,
        now=NOW + HABIT_CHECK_TTL,
    )
    assert [card["id"] for card in unpack(output)["habit_cards"]] == [new_card["id"]]
    assert len(requests) == 4


def test_discovery_expansion_reads_exact_full_record_or_single_scene_entry() -> None:
    payload = context()
    payload["knowledge_refs"] = [
        {
            "id": str(UUID(int=10)),
            "kind": "entity",
            "source": "knowledge",
            "revision": 4,
            "needs_expansion": True,
            "read": {
                "tool": "echome_knowledge_read",
                "arguments": {
                    "action": "get",
                    "record_id": str(UUID(int=10)),
                    "data": {"revision": 4},
                },
            },
        },
        {
            "id": str(UUID(int=11)),
            "kind": "scene_entry",
            "source": "scene",
            "revision": 2,
            "needs_expansion": True,
            "read": {
                "tool": "echome_scene_read",
                "arguments": {
                    "action": "get",
                    "selector": "home-network",
                },
            },
        },
    ]
    before = json.dumps(payload)
    references = task_hook._context_index(payload)["knowledge_refs"]
    assert references[0]["read"]["arguments"] == {
        "action": "get",
        "record_id": str(UUID(int=10)),
        "data": {"revision": 4},
        "view": "full",
    }
    assert references[1]["read"]["arguments"] == {
        "action": "get",
        "selector": "home-network",
        "entry_id": str(UUID(int=11)),
    }
    assert json.dumps(payload) == before


@pytest.mark.asyncio
async def test_browser_wrapping_does_not_change_query_or_same_task_cache(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    state_dir = tmp_path / "state"
    task = "修复登录页面，保留 https://bwm.example.test/login 入口"
    for index in range(2):
        raw = (
            '<in-app-browser-context source="ambient-ui-state">\n'
            f"Current URL: http://localhost:{61000 + index}/unrelated\n"
            "</in-app-browser-context>\n\n## My request:\n" + task
        )
        output = await run_hook(
            event(tmp_path, raw), config=CONFIG, state_dir=state_dir, now=NOW + index
        )
        assert bool(output) is (index == 0)
    assert len(requests) == 2
    assert json.loads(requests[-1].content)["task"] == task
    assert json.loads(requests[-1].content)["project_hint"] == str(tmp_path)
    continued = (
        "<in-app-browser-context>page context has changed</in-app-browser-context>\n"
        "## My request:\n请继续"
    )
    assert not await run_hook(
        event(tmp_path, continued), config=CONFIG, state_dir=state_dir, now=NOW + 2
    )
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_long_ambient_does_not_hide_short_task_or_trigger_web_habits(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    raw = (
        "<in-app-browser-context>\n"
        + "browser page context UI 改页面 " * 300
        + "\n</in-app-browser-context>\n## My request:\n配置 FlClash 与公司 VPN"
    )
    assert len(raw) > 4000
    pack = unpack(
        await run_hook(event(tmp_path, raw), config=CONFIG, state_dir=tmp_path / "state", now=NOW)
    )
    assert "habit_cards" not in pack
    assert json.loads(requests[-1].content)["task"] == "配置 FlClash 与公司 VPN"


@pytest.mark.asyncio
async def test_raw_input_limit_still_applies_before_ambient_removal(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    raw = (
        "<in-app-browser-context>"
        + "x" * task_hook.MAX_INPUT_BYTES
        + "</in-app-browser-context>\n修复登录页面"
    )
    assert not await run_hook(
        event(tmp_path, raw), config=CONFIG, state_dir=tmp_path / "state", now=NOW
    )
    assert not requests


@pytest.mark.asyncio
async def test_question_answer_semantics_are_sent_without_client_metadata(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    reply = json.dumps(
        [
            {
                "questionItemId": "PRIVATE_CLIENT_ID",
                "question": "项目用哪个部署版本？",
                "answer": "rc.8",
            }
        ],
        ensure_ascii=False,
    )
    raw = "<send_user_message_question_reply>" + reply + "</send_user_message_question_reply>"
    await run_hook(event(tmp_path, raw), config=CONFIG, state_dir=tmp_path / "state", now=NOW)
    assert json.loads(requests[-1].content)["task"] == "问题： 项目用哪个部署版本？\n回答： rc.8"
    assert "PRIVATE_CLIENT_ID" not in requests[-1].content.decode()


@pytest.mark.asyncio
async def test_sensitive_question_answer_is_not_sent_after_normalization(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    requests = transport()
    reply = json.dumps([{"question": "项目部署参数？", "answer": "password=SYNTHETIC_ONLY"}])
    raw = "<send_user_message_question_reply>" + reply + "</send_user_message_question_reply>"
    assert not await run_hook(
        event(tmp_path, raw), config=CONFIG, state_dir=tmp_path / "state", now=NOW
    )
    assert not requests


@pytest.mark.asyncio
async def test_old_hub_does_not_retry_full_context_and_records_missing_discovery(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("memories"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(404)

    requests = transport(respond)
    state_dir = tmp_path / "state"
    assert not await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    assert [r.url.path for r in requests] == ["/api/v1/memories", "/api/v1/context/discovery"]
    state = json.loads(next(state_dir.glob("*.json")).read_text())
    assert state["last_decision"] == {"action": "failure", "reason": "discovery_not_supported"}


def test_project_discovery_reference_keeps_canonical_identity() -> None:
    payload = empty_context() | {
        "scope": "project",
        "project_resolution": {"canonical_project_id": "qzhqzh/biomed"},
    }
    reference = task_hook._context_index(payload)["project_reference"]
    assert reference["project_hint"] == "qzhqzh/biomed"
    assert reference["tool"] == "echome_context" and reference["needs_expansion"] is True


def test_discovery_keeps_policy_warning_scope_and_knowledge_review_state() -> None:
    payload = context()
    intervention = {"action": "warn", "reason": "conflicting evidence; verify before reuse"}
    scope = {"global": False, "projects": ["qzhqzh/biomed"]}
    payload["memories"][0].update({"intervention": intervention, "scope": scope})
    payload["knowledge_refs"][0]["review_state"] = "disputed"
    payload["scope"] = "project"
    payload["project_resolution"] = {"canonical_project_id": "qzhqzh/biomed"}
    payload["project_reference"] = {
        "read": {
            "tool": "echome_context",
            "arguments": {"project_hint": "qzhqzh/biomed", "mode": "project"},
        },
        "notice": "Supply the current task when expanding these project constraints.",
    }
    result = task_hook._context_index(payload)
    assert result["memory_index"][0]["intervention"] == intervention
    assert result["memory_index"][0]["scope"] == scope
    assert result["knowledge_refs"][0]["review_state"] == "disputed"
    assert result["project_reference"]["read"] == payload["project_reference"]["read"]
    assert "Supply the current task" in result["project_reference"]["notice"]


def test_discovery_omits_empty_envelopes_and_repeated_project_identity() -> None:
    read = {
        "tool": "echome_context",
        "arguments": {"project_hint": "qzhqzh/BioWorkflowManage", "mode": "project", "as_of": None},
    }
    payload = empty_context() | {
        "scope": "project",
        "project_resolution": {
            "status": "resolved",
            "auto_resolved": True,
            "canonical_project_id": "qzhqzh/BioWorkflowManage",
            "project_context_available": True,
            "requires_confirmation": False,
        },
        "project_reference": {"needs_expansion": True, "tool": "echome_context", "read": read},
    }
    result = task_hook._context_index(payload)
    assert "memory_index" not in result and "knowledge_refs" not in result
    assert "project_resolution" not in result
    reference = result["project_reference"]
    assert "tool" not in reference and "project_hint" not in reference
    assert reference["read"] == read  # Including optional null read arguments.
    assert json.dumps(result).count("qzhqzh/BioWorkflowManage") == 1
    assert "Not a complete constraint pack" in result["notice"]


@pytest.mark.parametrize("status", ["ambiguous", "not_found"])
def test_discovery_keeps_unresolved_status_without_empty_project_values(status: str) -> None:
    payload = context() | {
        "project_resolution": {
            "status": status,
            "canonical_project_id": None,
            "auto_resolved": False,
            "project_context_available": False,
            "requires_confirmation": status == "ambiguous",
        }
    }
    result = task_hook._context_index(payload)
    assert result["project_resolution"]["status"] == status
    if status == "ambiguous":
        assert result["project_resolution"]["requires_confirmation"] is True
    assert "canonical_project_id" not in result["project_resolution"]


def test_projection_keeps_all_candidates_and_cautions_instead_of_reducing_results() -> None:
    payload = empty_context()
    payload["memory_index"] = [
        {
            "id": str(UUID(int=index + 100)),
            "title": f"记忆 {index}",
            "warning": None if index == 0 else {"reason": "核验当前状态"},
            "intervention": {"action": "warn", "reason": "conflicting evidence"},
        }
        for index in range(7)
    ]
    payload["knowledge_refs"] = [
        {
            "id": str(UUID(int=index + 200)),
            "title": f"资料 {index}",
            "review_state": "disputed",
            "warning": "保留冲突限定，不作为已确认规则",
            "read": {"tool": "echome_knowledge_read", "arguments": {"action": "history"}},
            "revision": None,
        }
        for index in range(6)
    ]
    result = task_hook._context_index(payload)
    for kind in ("memory_index", "knowledge_refs"):
        assert [item["id"] for item in result[kind]] == [item["id"] for item in payload[kind]]
        for before, after in zip(payload[kind], result[kind], strict=True):
            for key in ("warning", "intervention", "review_state", "read"):
                if before.get(key) is not None:
                    assert after[key] == before[key]
    assert "warning" not in result["memory_index"][0]
    assert "revision" not in result["knowledge_refs"][0]


@pytest.mark.asyncio
async def test_discovery_adds_only_sanitized_origin_without_persisting_credentials(
    tmp_path: Path, transport: Callable[..., list[httpx.Request]]
) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text(
        '[remote "origin"]\n'
        "url = https://SYNTHETIC_USER:SYNTHETIC_PASSWORD@github.com/qzhqzh/biomed.git?token=SYNTHETIC_QUERY\n"
    )
    requests = transport()
    state_dir = tmp_path / "state"
    await run_hook(event(tmp_path), config=CONFIG, state_dir=state_dir, now=NOW)
    body = json.loads(requests[-1].content)
    assert body["project_hint"] == str(tmp_path)
    assert body["project_hints"] == ["https://github.com/qzhqzh/biomed.git"]
    assert "SYNTHETIC_" not in requests[-1].content.decode()
    assert "SYNTHETIC_" not in next(state_dir.glob("*.json")).read_text()
