"""Memory gating is advisory, bounded, and never transmits common credentials."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from echome.core import memory_gate
from echome.core.client import HubClient
from echome.core.memory_gate import (
    GateDecision,
    GateRequest,
    GateSettings,
    build_systemone_payload,
    decide,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    real_client = httpx.AsyncClient

    def install(
        body: Any = None,
        *,
        status: int = 200,
        error: Exception | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[httpx.Request]:
        requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if error:
                raise error
            return httpx.Response(status, json=body, content=content, headers=headers)

        def client(**kwargs: Any) -> httpx.AsyncClient:
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            assert kwargs["timeout"].connect == 2.0
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        monkeypatch.setattr(memory_gate.httpx, "AsyncClient", client)
        return requests

    return install


def answer(choice: str, probabilities: dict[str, Any], confidence: float = 0.01) -> dict[str, Any]:
    return {
        "model": "untrusted response model",
        "answers": {
            "action": {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities,
                "confidence": confidence,
            }
        },
    }


@pytest.mark.parametrize(
    ("phase", "text", "action", "extra"),
    [
        ("read", "请修复登录页面", "retrieve", {}),
        ("read", "我们之前决定用什么数据库？", "retrieve", {}),
        ("read", "恢复这个项目上下文", "retrieve", {}),
        ("read", "What are my preferences?", "retrieve", {}),
        ("read", "What did we decide last time?", "retrieve", {}),
        ("read", "Translate hello to Chinese", "skip", {}),
        ("read", "翻译：Good morning", "skip", {}),
        ("read", "翻译这份文件，遵循项目风格", "retrieve", {}),
        ("read", "翻译，但按我以前的术语", "retrieve", {"context_available": True}),
        ("read", "Use my previous preferences", "retrieve", {"context_available": True}),
        ("read", "计算 2 + 2", "skip", {}),
        ("read", "继续修改按钮", "reuse", {"context_available": True}),
        ("read", "之前的项目规则是什么？", "retrieve", {"context_available": True}),
        ("write", "以后默认用中文回复", "propose", {}),
        ("write", "我们决定使用 PostgreSQL", "propose", {}),
        ("write", "I prefer concise answers", "propose", {}),
        ("write", "有人说“以后默认用中文回复”", "review", {}),
        ("write", "我们决定使用 PostgreSQL 吗？", "review", {}),
        ("write", "我偏好什么", "review", {}),
        ("write", "我们还没确定使用 PostgreSQL", "skip", {}),
        ("write", "以后别人喜欢使用 Redis", "review", {}),
        ("write", "我推测你偏好 Redis", "skip", {}),
        ("write", "今天先用 SQLite", "skip", {}),
        ("write", "Maybe we should always use Redis", "skip", {}),
        ("write", "如果以后使用 Redis，也许会更快", "skip", {}),
        ("write", "这个模块使用 Redis", "review", {}),
        ("write", "请修复登录页面", "review", {"context_available": True}),
    ],
)
async def test_rules(phase: str, text: str, action: str, extra: dict[str, Any]) -> None:
    result = await decide(GateRequest(phase=phase, text=text, **extra), GateSettings())
    assert result.action == action
    assert result.provider == "rules"
    assert result.shadow is True
    assert result.degraded is False
    assert result.model_probability is None


@pytest.mark.parametrize(
    ("phase", "explicit", "action"),
    [
        ("read", "read", "retrieve"),
        ("write", "remember", "propose"),
        ("read", "skip", "skip"),
        ("write", "skip", "skip"),
    ],
)
async def test_explicit_rules_precede_provider_and_context(
    provider: Callable[..., list[httpx.Request]], phase: str, explicit: str, action: str
) -> None:
    calls = provider(error=AssertionError("Explicit decisions must not call the model"))
    result = await decide(
        GateRequest(
            phase=phase, text="今天临时改一下", explicit_action=explicit, context_available=True
        ),
        GateSettings(provider="kev", base_url="http://127.0.0.1:8009"),
    )
    assert result.action == action
    assert result.reason_code == "explicit_" + explicit
    assert calls == []


@pytest.mark.parametrize(
    "text",
    [
        "api_key = 'synthetic-invalid-value'",
        'password: "synthetic-invalid-value"',
        "export SERVICE_TOKEN=synthetic-invalid-value",
        "sshpass -p 'synthetic-invalid-value' ssh example.invalid",
        "sshpass -o '-something' -psynthetic-invalid-value ssh example.invalid",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-invalid-key\n-----END OPENSSH PRIVATE KEY-----",
        "sk-proj-syntheticInvalidValue000000",
        "ghp_syntheticInvalidValue000000",
        "Authorization: Bearer synthetic-invalid-value",
        "密码是 synthetic-invalid-value",
        "https://user:synthetic-invalid-value@example.invalid",
        "https://example.invalid/path?token=synthetic-invalid-value",
    ],
)
@pytest.mark.parametrize("field", ["text", "project_hint"])
async def test_sensitive_input_never_transmitted_or_returned(
    provider: Callable[..., list[httpx.Request]],
    capsys: pytest.CaptureFixture[str],
    text: str,
    field: str,
) -> None:
    calls = provider(error=AssertionError("Sensitive input must not reach the model"))
    request = GateRequest.model_validate(
        {"phase": "write", "text": "记住这段内容", "explicit_action": "remember", field: text}
    )
    result = await decide(
        request, GateSettings(provider="laya", base_url="https://example.invalid")
    )
    assert (result.action, result.reason_code) == ("skip", "sensitive_input")
    assert calls == []
    assert text not in result.model_dump_json()
    assert text not in repr(request)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("kind", ["kev", "laya"])
async def test_choice_probability_and_payload(
    provider: Callable[..., list[httpx.Request]], kind: str
) -> None:
    calls = provider(answer("skip", {"retrieve": 0.1, "skip": 0.9}, confidence=0.1))
    request = GateRequest(phase="read", text="分析这段实现", project_hint="EchoMe")
    settings = GateSettings(
        provider=kind, base_url="http://192.168.1.20:8009/v1", api_key="synthetic-invalid-key"
    )
    result = await decide(request, settings)
    assert result.action == "skip"
    assert result.model_probability == 0.9
    assert result.model_action == "skip"
    assert result.degraded is False
    assert result.provider == kind
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert str(calls[0].url) == "http://192.168.1.20:8009/v1/systemone"
    assert calls[0].headers["authorization"] == "Bearer synthetic-invalid-key"
    assert json.loads(calls[0].content) == build_systemone_payload(request, settings)
    payload = json.loads(calls[0].content)
    assert payload["state"] == {"text": "分析这段实现", "project_hint": "EchoMe"}
    assert payload["questions"]["action"]["type"] == "choice"
    assert set(payload["questions"]["action"]["criteria"]) == {"retrieve", "skip"}
    assert result.model != "untrusted response model"


@pytest.mark.parametrize(("phase", "action"), [("read", "retrieve"), ("write", "review")])
@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "connect",
        "429",
        "malformed",
        "unknown",
        "nan",
        "negative",
        "sum",
        "winner",
        "bool",
        "missing",
        "infinite",
    ],
)
async def test_provider_failure_is_phase_safe(
    provider: Callable[..., list[httpx.Request]],
    capsys: pytest.CaptureFixture[str],
    phase: str,
    action: str,
    failure: str,
) -> None:
    valid = (
        {"retrieve": 0.9, "skip": 0.1}
        if phase == "read"
        else {"propose": 0.9, "skip": 0.1, "review": 0.0}
    )
    choice = "retrieve" if phase == "read" else "propose"
    kwargs: dict[str, Any] = {}
    if failure == "timeout":
        kwargs["error"] = httpx.ReadTimeout("synthetic-private-error")
    elif failure == "connect":
        kwargs["error"] = httpx.ConnectError("synthetic-private-error")
    elif failure == "429":
        kwargs.update(status=429, content=b"synthetic-private-error")
    elif failure == "malformed":
        kwargs["content"] = b"synthetic-private-error"
    elif failure == "unknown":
        choice = "write_to_hub"
    elif failure == "nan":
        # httpx JSON encoding correctly forbids NaN; simulate a malformed wire response.
        kwargs["content"] = json.dumps(answer(choice, {**valid, choice: float("nan")})).encode()
    elif failure == "infinite":
        kwargs["content"] = json.dumps(answer(choice, {**valid, choice: float("inf")})).encode()
    elif failure == "negative":
        valid["skip"] = -0.1
    elif failure == "sum":
        valid[choice] = 0.3
    elif failure == "winner":
        choice = "skip"
    elif failure == "bool":
        valid[choice] = True
    elif failure == "missing":
        del valid["skip"]
    calls = provider(answer(choice, valid), **kwargs)
    result = await decide(
        GateRequest(phase=phase, text="检查这段内容是否有帮助"),
        GateSettings(provider="kev", base_url="http://localhost:8009"),
    )
    assert len(calls) == 1
    assert result.action == action
    assert result.degraded is True
    assert result.model_probability is None
    assert "synthetic-private-error" not in result.model_dump_json()
    assert capsys.readouterr() == ("", "")


async def test_redirect_is_not_followed(provider: Callable[..., list[httpx.Request]]) -> None:
    calls = provider(status=307, headers={"Location": "https://untrusted.invalid"})
    result = await decide(
        GateRequest(phase="write", text="检查这段内容是否有帮助"),
        GateSettings(
            provider="kev", base_url="http://localhost:8009", api_key="synthetic-invalid-key"
        ),
    )
    assert len(calls) == 1
    assert result.action == "review"
    assert result.degraded is True


@pytest.mark.parametrize("phase", ["read", "write"])
async def test_low_probability_does_not_use_derived_confidence(
    provider: Callable[..., list[httpx.Request]], phase: str
) -> None:
    probabilities = (
        {"skip": 0.6, "retrieve": 0.4}
        if phase == "read"
        else {"propose": 0.6, "skip": 0.3, "review": 0.1}
    )
    provider(answer("skip" if phase == "read" else "propose", probabilities, confidence=1.0))
    result = await decide(
        GateRequest(phase=phase, text="检查这段内容是否有帮助"),
        GateSettings(provider="laya", base_url="http://localhost:8009"),
    )
    assert result.action == ("retrieve" if phase == "read" else "review")
    assert result.reason_code == "low_probability"
    assert result.model_probability == 0.6
    assert result.model_action == ("skip" if phase == "read" else "propose")


async def test_rounded_distribution_and_no_write_side_effects(
    provider: Callable[..., list[httpx.Request]], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Gate must not instantiate HubClient")

    monkeypatch.setattr(HubClient, "__init__", forbidden)
    monkeypatch.chdir(tmp_path)
    calls = provider(answer("propose", {"propose": 0.85, "skip": 0.08, "review": 0.08}))
    result = await decide(
        GateRequest(phase="write", text="检查这段内容是否有帮助"),
        GateSettings(provider="kev", base_url="http://localhost:8009"),
    )
    assert result.action == "propose"
    assert result.shadow is True
    assert result.model_probability == 0.85
    assert list(tmp_path.iterdir()) == []
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/systemone"
    assert "authorization" not in calls[0].headers
    assert set(json.loads(calls[0].content)["questions"]["action"]["criteria"]) == {
        "propose",
        "skip",
        "review",
    }
    assert set(result.model_dump()) == {
        "schema_version",
        "decision_id",
        "phase",
        "action",
        "provider",
        "reason_code",
        "model_probability",
        "model_action",
        "latency_ms",
        "model",
        "degraded",
        "shadow",
    }


async def test_overall_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.AsyncClient

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=answer("skip", {"retrieve": 0.1, "skip": 0.9}))

    monkeypatch.setattr(
        memory_gate.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(slow), **kwargs),
    )
    result = await decide(
        GateRequest(phase="read", text="检查这段内容是否有帮助"),
        GateSettings(provider="kev", base_url="http://localhost:8009", timeout_seconds=0.1),
    )
    assert result.action == "retrieve"
    assert result.reason_code == "provider_timeout"
    assert result.latency_ms < 900


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8009",
        "http://127.0.0.1:8009/",
        "http://192.168.2.10",
        "http://10.0.0.2/v1",
        "http://172.16.0.2",
        "http://[::1]:8009",
        "http://[fd00::1]:8009",
        "https://model.example.invalid",
    ],
)
async def test_explicit_provider_urls(url: str) -> None:
    assert GateSettings(base_url=url).base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "http://8.8.8.8",
        "http://169.254.169.254",
        "http://0.0.0.0",
        "https://user:synthetic-invalid-value@example.com",
        "https://example.com?token=synthetic-invalid-value",
        "https://example.com#fragment",
        "https://example.com?",
        "file:///tmp/model",
        "http://localhost:99999",
        "http://localhost\\@example.com",
        "http://localhost\n",
    ],
)
async def test_unsafe_urls_rejected_without_echoing_input(url: str) -> None:
    with pytest.raises(ValidationError) as exc:
        GateSettings(base_url=url)
    assert url not in str(exc.value)
    assert "synthetic-invalid-value" not in str(exc.value)


async def test_schema_and_bounds() -> None:
    assert (
        GateRequest.model_validate(
            {"schema": "echome.memory-gate.v1", "phase": "read", "text": "hello"}
        ).schema_version
        == "echome.memory-gate.v1"
    )
    for text in ("", "  ", "x" * 4001):
        with pytest.raises(ValidationError):
            GateRequest(phase="read", text=text)
    for invalid in (
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"threshold": 1.1},
        {"threshold": float("nan")},
    ):
        with pytest.raises(ValidationError):
            GateSettings(**invalid)
    for phase, explicit in (("read", "remember"), ("write", "read")):
        with pytest.raises(ValidationError, match="must match"):
            GateRequest(phase=phase, text="hello", explicit_action=explicit)
    for model in ("bad\nmodel", "sk-proj-syntheticInvalidValue000000", "../../tmp/model"):
        with pytest.raises(ValidationError):
            GateSettings(model=model)
    settings = GateSettings(api_key="synthetic-invalid-value")
    assert "synthetic-invalid-value" not in repr(settings)
    assert "api_key" not in settings.model_dump()
    with pytest.raises(ValidationError):
        GateDecision(
            phase="read",
            action="retrieve",
            provider="rules",
            reason_code="test",
            latency_ms=1,
            shadow=False,
        )


@pytest.mark.parametrize("phase", ["read", "write"])
async def test_missing_provider_config_falls_back(phase: str) -> None:
    result = await decide(
        GateRequest(phase=phase, text="检查这段内容是否有帮助"), GateSettings(provider="kev")
    )
    assert result.action == ("retrieve" if phase == "read" else "review")
    assert result.reason_code == "provider_not_configured"
    assert result.degraded is True
