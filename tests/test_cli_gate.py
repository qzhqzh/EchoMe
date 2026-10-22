"""Gate CLI cannot execute memory operations or disclose request contents."""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echome.commands import gate
from echome.commands.gate import append_audit
from echome.core.memory_gate import GateDecision, GateRequest, GateSettings
from echome.main import app

runner = CliRunner()


def test_stdin_decision_and_private_audit(tmp_path: Path) -> None:
    audit = tmp_path / "private" / "audit.jsonl"
    text = "以后默认用中文回复。"
    result = runner.invoke(
        app,
        ["gate", "decide", "--audit", str(audit), "--event-id", "task-123"],
        input=json.dumps({"phase": "write", "text": text}),
    )
    assert result.exit_code == 0, result.output
    decision = json.loads(result.stdout)
    assert decision["action"] == "propose"
    assert decision["shadow"] is True
    assert text not in result.stdout
    record = json.loads(audit.read_text())
    assert record["execution"] == "shadow_only"
    assert record["event_id"] == "task-123"
    assert text not in audit.read_text()
    assert audit.stat().st_mode & 0o777 == 0o600


def test_file_request(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"phase": "read", "text": "17+23"}))
    result = runner.invoke(app, ["gate", "decide", "--input", str(request)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["action"] == "skip"


@pytest.mark.parametrize(
    "payload",
    [
        '{"secret-like-extra-field": "do not echo"}',
        '{"phase":"unknown","text":"password=DEMO_ONLY"}',
        '{"phase":"read","text":"password=DEMO_ONLY",',
        "x" * 65537,
    ],
)
def test_invalid_input_is_not_echoed(payload: str) -> None:
    result = runner.invoke(app, ["gate", "decide"], input=payload)
    assert result.exit_code == 2
    assert "DEMO_ONLY" not in result.output
    assert "secret-like-extra-field" not in result.output


def test_sensitive_input_never_calls_model() -> None:
    result = runner.invoke(
        app,
        ["gate", "decide", "--provider", "kev", "--base-url", "http://127.0.0.1:1"],
        input=json.dumps(
            {
                "phase": "write",
                "text": "sshpass -p DEMO_ONLY ssh localhost",
                "explicit_action": "remember",
            }
        ),
    )
    assert result.exit_code == 0, result.output
    decision = json.loads(result.stdout)
    assert decision["reason_code"] == "sensitive_input"
    assert decision["provider"] == "rules"
    assert "DEMO_ONLY" not in result.stdout


@pytest.mark.parametrize("override", [None, "CUSTOM_DECISION_KEY"])
def test_jev_uses_separate_key_environment(
    monkeypatch: pytest.MonkeyPatch, override: str | None
) -> None:
    captured: list[GateSettings] = []

    async def inspect(request: GateRequest, settings: GateSettings) -> GateDecision:
        captured.append(settings)
        return GateDecision(
            phase=request.phase,
            action="retrieve",
            provider="jev",
            reason_code="test",
            latency_ms=0,
        )

    monkeypatch.setattr(gate, "decide", inspect)
    monkeypatch.setenv("ECHOME_AUTH_TOKEN", "hub-credential-must-not-be-used")
    monkeypatch.setenv("ECHOME_GATE_API_KEY", "old-provider-key-must-not-be-used")
    monkeypatch.setenv("ECHOME_GATE_JEV_API_KEY", "synthetic-jev-key")
    monkeypatch.setenv("CUSTOM_DECISION_KEY", "synthetic-custom-key")
    args = ["gate", "decide", "--provider", "jev", "--base-url", "https://api.typesafe.ai"]
    if override:
        args.extend(["--api-key-env", override])
    result = runner.invoke(app, args, input='{"phase":"read","text":"分析这段实现"}')
    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0].api_key == ("synthetic-custom-key" if override else "synthetic-jev-key")
    assert captured[0].timeout_seconds == 2.0
    assert "key" not in result.stdout
    assert "credential" not in result.stdout


def test_audit_refuses_public_file_and_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("original")
    target.chmod(0o644)
    with pytest.raises(ValueError):
        append_audit(target, {}, None)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        append_audit(link, {}, None)
    assert target.read_text() == "original"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_audit_does_not_block_on_fifo(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises((ValueError, OSError)):
        append_audit(fifo, {}, None)


def test_public_audit_failure_is_explicit(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.touch(mode=0o644)
    result = runner.invoke(
        app, ["gate", "decide", "--audit", str(audit)], input='{"phase":"read","text":"2+2"}'
    )
    assert result.exit_code == 1
    assert "Could not append private gate audit" in result.output
    assert audit.read_text() == ""
