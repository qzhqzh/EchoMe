"""The hook command emits only nonblocking JSON, never user text or secrets."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from echome.commands import hook
from echome.core import task_hook
from echome.core.config import Config
from echome.main import app

runner = CliRunner()


@pytest.mark.parametrize(
    "payload",
    [
        "not-json-secret-text",
        "[]",
        '{"prompt":"secret-text"',
        "x" * 65537,
    ],
)
def test_invalid_envelope_fails_open_without_echo(payload: str) -> None:
    result = runner.invoke(app, ["hook", "codex"], input=payload)
    assert result.exit_code == 0
    assert result.stdout.strip() == "{}"
    assert "secret-text" not in result.output


def test_invalid_marker_does_not_run_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*args: Any, **kwargs: Any) -> dict[str, Any]:
        pytest.fail("invalid marker must not invoke adapter")

    monkeypatch.setattr(task_hook, "run_hook", forbidden)
    result = runner.invoke(app, ["hook", "codex", "--managed-by", "other"], input="{}")
    assert result.exit_code == 0 and result.stdout.strip() == "{}"


def test_adapter_exception_never_leaks_prompt_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("SYNTHETIC_SERVER_TOKEN sensitive prompt")

    monkeypatch.setattr(Config, "load", lambda: Config(token="SYNTHETIC_HUB_TOKEN"))
    monkeypatch.setattr(task_hook, "run_hook", failing)
    result = runner.invoke(app, ["hook", "codex"], input=json.dumps({"prompt": "sensitive prompt"}))
    assert result.exit_code == 0 and result.stdout.strip() == "{}"
    assert "SYNTHETIC" not in result.output
    assert "sensitive prompt" not in result.output


def test_cli_passes_event_and_separate_optional_model_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def inspect(event: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured.update(event=event, **kwargs)
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "test data",
            }
        }

    monkeypatch.setattr(Config, "load", lambda: Config(token="SYNTHETIC_HUB_TOKEN"))
    monkeypatch.setattr(task_hook, "run_hook", inspect)
    monkeypatch.setattr(hook.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("ECHOME_HOOK_GATE_PROVIDER", "jev")
    monkeypatch.setenv("ECHOME_HOOK_GATE_URL", "https://model.example.test")
    monkeypatch.setenv("ECHOME_GATE_JEV_API_KEY", "SYNTHETIC_MODEL_KEY")
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "prompt": "修改页面",
    }
    result = runner.invoke(
        app, ["hook", "codex", "--managed-by", "echome-v1"], input=json.dumps(payload)
    )
    assert result.exit_code == 0
    assert captured["event"] == payload
    assert captured["config"].token == "SYNTHETIC_HUB_TOKEN"
    assert captured["gate"].api_key == "SYNTHETIC_MODEL_KEY"
    assert captured["gate"].timeout_seconds <= 1
    assert captured["state_dir"] == tmp_path / ".echome" / "hook-state"
    assert json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"] == "test data"
    assert "SYNTHETIC" not in result.output
