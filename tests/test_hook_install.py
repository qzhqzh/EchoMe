"""Codex hook installation preserves other integrations and never grants trust."""

import json
import os
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from echome.core import hook_install
from echome.core.hook_install import EVENTS, hook_status, install_hooks, remove_hooks


@pytest.fixture(autouse=True)
def private_test_files() -> Iterator[None]:
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def executable(tmp_path: Path, name: str = "echome binary") -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 99\n")
    path.chmod(0o700)
    return path


def read_config(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "hooks.json").read_text())


def test_install_is_private_bounded_and_idempotent(tmp_path: Path) -> None:
    directory = tmp_path / "codex"
    binary = executable(tmp_path)
    result = install_hooks(directory, executable=binary)
    assert result["changed"] and result["complete"]
    assert result["backup_path"] is None
    assert result["trust_status"] == "not_checked"
    assert result["trust_modified"] is False
    assert directory.stat().st_mode & 0o777 == 0o700
    path = directory / "hooks.json"
    assert path.stat().st_mode & 0o777 == 0o600
    original = path.read_bytes()
    for event in EVENTS:
        handler = read_config(directory)["hooks"][event][0]["hooks"][0]
        assert shlex.split(handler["command"]) == [
            str(binary),
            "hook",
            "codex",
            "--managed-by",
            "echome-v1",
        ]
        assert handler["timeout"] == 5
        assert type(handler["timeout"]) is int
        assert handler["additionalContextLimit"] == 6000
        assert set(handler) == {"type", "command", "timeout", "additionalContextLimit"}
    repeated = install_hooks(directory, executable=binary)
    assert not repeated["changed"]
    assert path.read_bytes() == original
    assert not list(directory.glob(".echome-hooks.backup.*"))


def test_install_remove_preserves_unknown_fields_and_mixed_hooks(tmp_path: Path) -> None:
    binary = executable(tmp_path)
    secret_handler = {"type": "command", "command": "other-agent --token SYNTHETIC_ONLY"}
    old_own = {
        "type": "command",
        "command": "/retired/echome hook codex --managed-by echome-v1",
        "timeout": 20,
    }
    original = {
        "custom": {"trust": "unrelated-value", "extra": [1, 2]},
        "hooks": {
            "UserPromptSubmit": [{"matcher": "*", "hooks": [old_own, secret_handler]}],
            "SessionStart": [{"hooks": [old_own]}, {"hooks": [old_own]}],
            "FutureEvent": {"unknown": "preserve exactly"},
        },
    }
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps(original, separators=(",", ":")))
    old_bytes = path.read_bytes()
    result = install_hooks(tmp_path, executable=binary)
    backup = Path(result["backup_path"])
    assert backup.read_bytes() == old_bytes
    assert backup.stat().st_mode & 0o777 == 0o600
    assert result["events"] == dict.fromkeys(EVENTS, 1)
    installed = read_config(tmp_path)
    assert installed["custom"] == original["custom"]
    assert installed["hooks"]["FutureEvent"] == original["hooks"]["FutureEvent"]
    assert installed["hooks"]["UserPromptSubmit"][0] == {"matcher": "*", "hooks": [secret_handler]}
    status = hook_status(tmp_path)
    assert status["complete"]
    assert "SYNTHETIC_ONLY" not in json.dumps(status)
    removed = remove_hooks(tmp_path)
    assert removed["changed"] and not removed["installed"]
    assert Path(removed["backup_path"]).read_text() == json.dumps(installed, indent=2) + "\n"
    assert read_config(tmp_path) == {
        "custom": original["custom"],
        "hooks": {
            "UserPromptSubmit": [{"matcher": "*", "hooks": [secret_handler]}],
            "FutureEvent": original["hooks"]["FutureEvent"],
        },
    }
    assert not remove_hooks(tmp_path)["changed"]


@pytest.mark.parametrize(
    "command",
    [
        "echo '/old/echome hook codex --managed-by echome-v1'",
        "/old/echome hook codex",
        "/old/echome hook codex --managed-by another-owner",
        "/old/echome hook codex --managed-by echome-v1 && echo other",
        "/old/echome hook codex --managed-by echome-v1 --extra",
        "echome hook codex --managed-by echome-v1",
        "'unterminated",
    ],
)
def test_remove_only_exact_owned_commands(tmp_path: Path, command: str) -> None:
    payload = {
        "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}
    }
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps(payload))
    raw = path.read_bytes()
    assert not remove_hooks(tmp_path)["changed"]
    assert path.read_bytes() == raw


def test_remove_retains_unknown_group_metadata(tmp_path: Path) -> None:
    payload = {
        "hooks": {
            "SessionStart": [
                {
                    "extension": {"keep": True},
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/old/echome hook codex --managed-by echome-v1",
                        }
                    ],
                }
            ]
        }
    }
    (tmp_path / "hooks.json").write_text(json.dumps(payload))
    remove_hooks(tmp_path)
    assert read_config(tmp_path)["hooks"]["SessionStart"] == [
        {"extension": {"keep": True}, "hooks": []}
    ]


def test_missing_status_and_remove_do_not_create_directory(tmp_path: Path) -> None:
    missing = tmp_path / "not-created"
    assert not hook_status(missing)["installed"]
    assert not remove_hooks(missing)["changed"]
    assert not missing.exists()


def test_rejects_symlinks_in_config_and_directory(tmp_path: Path) -> None:
    original = tmp_path / "original.json"
    original.write_text('{"keep":true}')
    directory = tmp_path / "codex"
    directory.mkdir()
    (directory / "hooks.json").symlink_to(original)
    for operation in (hook_status, remove_hooks):
        with pytest.raises((OSError, ValueError)):
            operation(directory)
    with pytest.raises((OSError, ValueError)):
        install_hooks(directory, executable=Path(sys.executable))
    assert original.read_text() == '{"keep":true}'
    link = tmp_path / "codex-link"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        install_hooks(link, executable=Path(sys.executable))
    with pytest.raises(ValueError, match="symbolic"):
        install_hooks(link / "nested", executable=Path(sys.executable))
    assert not (directory / "nested").exists()


def test_rejects_unsafe_permissions_and_hard_links(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    path.write_text("{}")
    path.chmod(0o666)
    with pytest.raises(ValueError, match="permissions"):
        hook_status(tmp_path)
    path.chmod(0o600)
    os.link(path, tmp_path / "hard-link")
    with pytest.raises(ValueError, match="hard links"):
        remove_hooks(tmp_path)
    unsafe = tmp_path / "unsafe-directory"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    with pytest.raises(ValueError, match="writable"):
        install_hooks(unsafe, executable=Path(sys.executable))


def test_current_user_group_writable_directory_is_supported_without_chmod(tmp_path: Path) -> None:
    directory = tmp_path / "codex"
    directory.mkdir(mode=0o700)
    directory.chmod(0o775)
    assert directory.stat().st_gid == os.getgid()
    result = install_hooks(directory, executable=Path(sys.executable))
    assert result["complete"] and result["changed"]
    assert directory.stat().st_mode & 0o777 == 0o775
    assert (directory / "hooks.json").stat().st_mode & 0o777 == 0o600
    assert hook_status(directory)["complete"]
    assert remove_hooks(directory)["changed"]
    assert directory.stat().st_mode & 0o777 == 0o775


def test_other_group_writable_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "codex"
    directory.mkdir(mode=0o700)
    directory.chmod(0o775)
    foreign_group = directory.stat().st_gid + 1
    monkeypatch.setattr(hook_install.os, "getgid", lambda: foreign_group)
    with pytest.raises(ValueError, match="another group"):
        install_hooks(directory, executable=Path(sys.executable))
    assert not (directory / "hooks.json").exists()
    assert directory.stat().st_mode & 0o777 == 0o775


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_refuses_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "hooks.json", 0o600)
    with pytest.raises(ValueError, match="regular"):
        hook_status(tmp_path)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"hooks":null}',
        '{"hooks":{"SessionStart":{}}}',
        '{"hooks":{"UserPromptSubmit":[{}]}}',
        '{"hooks":{"SessionStart":[{"hooks":[1]}]}}',
        '{"hooks":{},"hooks":{}}',
    ],
)
def test_invalid_config_is_not_overwritten(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "hooks.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        install_hooks(tmp_path, executable=Path(sys.executable))
    assert path.read_text() == raw
    assert not list(tmp_path.glob(".echome-hooks.backup.*"))


@pytest.mark.parametrize("timeout", [0, -1, 0.5, 1.5, 4.9, 5.1, float("nan"), float("inf"), True])
def test_timeout_rejects_unbounded_settings(tmp_path: Path, timeout: float) -> None:
    directory = tmp_path / "codex"
    with pytest.raises(ValueError, match="five seconds"):
        install_hooks(directory, executable=Path(sys.executable), timeout=timeout)
    assert not directory.exists()


def test_reinstall_repairs_legacy_float_timeout_and_then_is_idempotent(tmp_path: Path) -> None:
    binary = executable(tmp_path)
    install_hooks(tmp_path, executable=binary, timeout=5.0)
    payload = read_config(tmp_path)
    for groups in payload["hooks"].values():
        groups[0]["hooks"][0]["timeout"] = 5.0
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps(payload))
    original = path.read_bytes()
    repaired = install_hooks(tmp_path, executable=binary, timeout=5.0)
    assert repaired["changed"]
    assert Path(repaired["backup_path"]).read_bytes() == original
    for groups in read_config(tmp_path)["hooks"].values():
        assert type(groups[0]["hooks"][0]["timeout"]) is int
    assert not install_hooks(tmp_path, executable=binary, timeout=5.0)["changed"]


def test_explicit_command_and_installed_binary_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = executable(tmp_path)
    monkeypatch.setattr(hook_install.shutil, "which", lambda _: str(binary))
    assert install_hooks(tmp_path)["complete"]
    assert not install_hooks(tmp_path, command=[str(binary), "hook", "codex"])["changed"]
    with pytest.raises(ValueError, match="not both"):
        install_hooks(tmp_path, executable=binary, command=[str(binary), "hook", "codex"])
    with pytest.raises(ValueError, match="absolute"):
        install_hooks(tmp_path, command=["echome", "hook", "codex"])
    with pytest.raises(ValueError, match="Explicit command"):
        install_hooks(tmp_path, command=[str(binary), "dangerous-other-command"])


def test_default_prefers_lightweight_helper_and_falls_back_to_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = executable(tmp_path, "echome-hook")
    cli = executable(tmp_path, "echome")
    available = {"echome-hook": str(helper), "echome": str(cli)}
    monkeypatch.setattr(hook_install.shutil, "which", available.get)
    install_hooks(tmp_path)
    handler = read_config(tmp_path)["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert shlex.split(handler["command"])[0] == str(helper)
    available.pop("echome-hook")
    assert install_hooks(tmp_path)["changed"]
    handler = read_config(tmp_path)["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert shlex.split(handler["command"])[0] == str(cli)


def test_atomic_replace_failure_leaves_original_and_private_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "hooks.json"
    path.write_bytes(b'{"unknown": [1, 2]}\n')
    original = path.read_bytes()

    def fail_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(hook_install.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        install_hooks(tmp_path, executable=Path(sys.executable))
    assert path.read_bytes() == original
    backups = list(tmp_path.glob(".echome-hooks.backup.*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".echome-hooks.*.tmp"))


def test_detects_concurrent_non_echome_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "hooks.json"
    path.write_text("{}")
    original_write = hook_install._write_private

    def write_and_modify(directory_fd: int, name: str, content: bytes) -> None:
        original_write(directory_fd, name, content)
        if name.endswith(".tmp"):
            path.write_text('{"concurrent":"preserved"}')

    monkeypatch.setattr(hook_install, "_write_private", write_and_modify)
    with pytest.raises(ValueError, match="concurrently"):
        install_hooks(tmp_path, executable=Path(sys.executable))
    assert path.read_text() == '{"concurrent":"preserved"}'
    assert not list(tmp_path.glob(".echome-hooks.*.tmp"))


def test_busy_installer_fails_without_waiting(tmp_path: Path) -> None:
    import fcntl

    lock = tmp_path / ".echome-hooks.lock"
    with lock.open("w") as stream:
        lock.chmod(0o600)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="in progress"):
            install_hooks(tmp_path, executable=Path(sys.executable))
    assert not (tmp_path / "hooks.json").exists()
