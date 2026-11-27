"""Install only EchoMe-owned Codex hook commands, without changing Codex trust."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

EVENTS = ("UserPromptSubmit", "SessionStart")
MANAGED_BY = "echome-v1"
HOOK_FILE = "hooks.json"
MAX_CONFIG_BYTES = 1024 * 1024
DEFAULT_CONTEXT_LIMIT = 6000


def _private_regular(info: os.stat_result, *, private: bool = False) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Hook configuration must be a regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("Hook configuration must belong to the current user")
    if stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022):
        raise ValueError("Hook configuration has unsafe permissions")
    if info.st_nlink != 1:
        raise ValueError("Hook configuration must not have multiple hard links")


def _target_path(target_dir: Path) -> Path:
    path = Path(os.path.abspath(target_dir.expanduser()))
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Hook configuration directories must not be symbolic links")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Hook configuration directory is not a directory")
    return path


@contextmanager
def _directory(target_dir: Path, *, create: bool) -> Iterator[tuple[Path, int | None]]:
    if os.name != "posix":
        raise ValueError("This hook installer currently requires a POSIX filesystem")
    path = _target_path(target_dir)
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    elif not path.exists():
        yield path, None
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("Hook configuration directory must belong to the current user")
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o002 or (mode & 0o020 and info.st_gid != os.getgid()):
            raise ValueError(
                "Hook configuration directory must not be world-writable or writable by another group"
            )
        yield path, descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _locked(directory_fd: int) -> Iterator[None]:
    # This installer targets POSIX filesystems. The advisory lock only serializes
    # EchoMe installers; the file identity check also detects other edits.
    import fcntl

    descriptor = os.open(
        ".echome-hooks.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        _private_regular(os.fstat(descriptor), private=True)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another EchoMe hook configuration update is in progress") from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Hook configuration contains duplicate JSON keys")
        result[key] = value
    return result


def _read(directory_fd: int) -> tuple[dict[str, Any], bytes | None, os.stat_result | None]:
    try:
        descriptor = os.open(
            HOOK_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
        )
    except FileNotFoundError:
        return {}, None, None
    try:
        info = os.fstat(descriptor)
        _private_regular(info)
        if info.st_size > MAX_CONFIG_BYTES:
            raise ValueError("Hook configuration exceeds 1 MiB")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("Hook configuration exceeds 1 MiB")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Hook configuration is not valid UTF-8 JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("Hook configuration must be a JSON object")
    _groups(payload)
    return payload, raw, info


def _groups(payload: dict[str, Any]) -> dict[str, Any]:
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Hook configuration hooks must be an object")
    for event in EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError("Hook event configuration must be a list")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("Hook event groups must contain a hooks list")
            if any(not isinstance(handler, dict) for handler in group["hooks"]):
                raise ValueError("Hook handlers must be objects")
    return hooks


def _owned(handler: dict[str, Any]) -> bool:
    if handler.get("type") != "command" or not isinstance(handler.get("command"), str):
        return False
    try:
        argv = shlex.split(handler["command"], posix=True)
    except ValueError:
        return False
    return (
        len(argv) == 5
        and Path(argv[0]).is_absolute()
        and argv[1:] == ["hook", "codex", "--managed-by", MANAGED_BY]
    )


def _without_owned(payload: dict[str, Any]) -> dict[str, Any]:
    # Copy only the containers we change. Unknown fields and other event handlers
    # are retained verbatim as JSON values, and no configured command is executed.
    result = dict(payload)
    hooks = dict(_groups(payload))
    for event in EVENTS:
        if event not in hooks:
            continue
        remaining = []
        for group in hooks[event]:
            handlers = [handler for handler in group["hooks"] if not _owned(handler)]
            if handlers == group["hooks"]:
                remaining.append(group)
            elif handlers or set(group) - {"hooks", "matcher"}:
                remaining.append({**group, "hooks": handlers})
        if remaining:
            hooks[event] = remaining
        else:
            hooks.pop(event)
    if "hooks" in payload or hooks:
        result["hooks"] = hooks
    return result


def _meta(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    hooks = _groups(payload)
    counts = {
        event: sum(_owned(handler) for group in hooks.get(event, []) for handler in group["hooks"])
        for event in EVENTS
    }
    return {
        "hooks_path": str(path / HOOK_FILE),
        "installed": any(counts.values()),
        "complete": all(count == 1 for count in counts.values()),
        "events": counts,
        "changed": False,
        "backup_path": None,
        "trust_status": "not_checked",
        "trust_managed_by": "codex",
        "trust_modified": False,
    }


def _same_file(current: os.stat_result | None, previous: os.stat_result | None) -> bool:
    if current is None or previous is None:
        return current is previous
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_uid")
    return all(getattr(current, field) == getattr(previous, field) for field in fields)


def _check_unchanged(directory_fd: int, previous: os.stat_result | None) -> None:
    try:
        current = os.stat(HOOK_FILE, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        current = None
    if not _same_file(current, previous):
        raise ValueError("Hook configuration changed concurrently; retry after checking it")


def _write_private(directory_fd: int, name: str, content: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save(
    directory_fd: int,
    path: Path,
    payload: dict[str, Any],
    raw: bytes | None,
    previous: os.stat_result | None,
) -> str | None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError("Updated hook configuration exceeds 1 MiB")
    _check_unchanged(directory_fd, previous)
    backup_name = f".echome-hooks.backup.{uuid4().hex}.json" if raw is not None else None
    if backup_name is not None and raw is not None:
        _write_private(directory_fd, backup_name, raw)
    temporary = f".echome-hooks.{uuid4().hex}.tmp"
    try:
        _write_private(directory_fd, temporary, content)
        _check_unchanged(directory_fd, previous)
        os.replace(temporary, HOOK_FILE, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory_fd)
    return str(path / backup_name) if backup_name else None


def _command(executable: Path | None, command: Sequence[str] | None) -> str:
    """Prefer the lightweight installed helper, retaining the standard CLI fallback."""
    if executable is not None and command is not None:
        raise ValueError("Specify executable or command, not both")
    if command is not None:
        if isinstance(command, str) or len(command) != 3 or list(command[1:]) != ["hook", "codex"]:
            raise ValueError(
                "Explicit command must be an absolute executable followed by hook codex"
            )
        binary = Path(command[0])
    else:
        located = (
            str(executable)
            if executable is not None
            else shutil.which("echome-hook") or shutil.which("echome")
        )
        if not located:
            raise ValueError("An installed EchoMe executable was not found")
        binary = Path(located)
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("EchoMe executable must be an absolute path to an executable file")
    return shlex.join([str(binary), "hook", "codex", "--managed-by", MANAGED_BY])


def install_hooks(
    target_dir: Path,
    *,
    executable: Path | None = None,
    command: Sequence[str] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Install bounded handlers using echome-hook when available, otherwise echome.

    Codex must handle trust through its user flow; this installer never grants it.
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 1 <= timeout <= 5
        or int(timeout) != timeout
    ):
        raise ValueError("Hook timeout must be a whole number from one to five seconds")
    command_text = _command(executable, command)
    with _directory(target_dir, create=True) as (path, directory_fd):
        assert directory_fd is not None
        with _locked(directory_fd):
            original, raw, previous = _read(directory_fd)
            updated = _without_owned(original)
            hooks = updated.setdefault("hooks", {})
            for event in EVENTS:
                hooks.setdefault(event, []).append(
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": command_text,
                                "timeout": int(timeout),
                                "additionalContextLimit": DEFAULT_CONTEXT_LIMIT,
                            }
                        ]
                    }
                )
            result = _meta(path, updated)
            # Python considers 5.0 == 5, but Codex's native u64 deserializer rejects
            # JSON 5.0. Compare serialized values so reinstall repairs legacy floats.
            if json.dumps(updated, sort_keys=True) != json.dumps(original, sort_keys=True):
                result["backup_path"] = _save(directory_fd, path, updated, raw, previous)
                result["changed"] = True
            return result


def remove_hooks(target_dir: Path) -> dict[str, Any]:
    """Remove exact EchoMe commands without deleting the config or other hooks."""
    with _directory(target_dir, create=False) as (path, directory_fd):
        if directory_fd is None:
            return _meta(path, {})
        with _locked(directory_fd):
            original, raw, previous = _read(directory_fd)
            updated = _without_owned(original)
            result = _meta(path, updated)
            if updated != original:
                result["backup_path"] = _save(directory_fd, path, updated, raw, previous)
                result["changed"] = True
            return result


def hook_status(target_dir: Path) -> dict[str, Any]:
    """Inspect ownership only; do not expose unrelated commands or infer user trust."""
    with _directory(target_dir, create=False) as (path, directory_fd):
        if directory_fd is None:
            return _meta(path, {})
        payload, _, _ = _read(directory_fd)
        return _meta(path, payload)
