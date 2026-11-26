"""Bounded local Git identity hints for automatic memory discovery.

Only repository metadata is read. Git is never invoked, config includes are not
followed, and URL credentials are removed before a hint can leave this module.
"""

from __future__ import annotations

import configparser
import os
import re
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from echome.core.gate_safety import contains_sensitive_input

MAX_PARENT_LEVELS = 8
MAX_CONFIG_BYTES = 65536
MAX_POINTER_BYTES = 4096
MAX_REMOTE_CHARS = 2048
_SCP_REMOTE = re.compile(r"(?:[^/@:\s]+@)?(?P<host>[^/:\s]+):(?P<path>[^\s]+)")


def _read_regular(path: Path, limit: int) -> str | None:
    """Reject symlinks/special files and bound actual reads, not just stat size."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                return None
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                return None
            return raw.decode("utf-8")
        finally:
            os.close(descriptor)
    except (OSError, UnicodeError, ValueError):
        return None


def _pointer(base: Path, text: str) -> Path | None:
    value = text.strip()
    if not value or len(value) > MAX_POINTER_BYTES or "\n" in value or "\x00" in value:
        return None
    path = Path(value)
    return Path(os.path.normpath(path if path.is_absolute() else base / path))


def _git_directory(marker: Path) -> Path | None:
    try:
        info = marker.lstat()
        if stat.S_ISDIR(info.st_mode):
            return marker
        if not stat.S_ISREG(info.st_mode):
            return None
        text = _read_regular(marker, MAX_POINTER_BYTES)
        if text is None or not text.startswith("gitdir:"):
            return None
        directory = _pointer(marker.parent, text.removeprefix("gitdir:"))
        if directory is None or directory.is_symlink() or not directory.is_dir():
            return None
        # Linked worktrees keep shared config in commondir; follow this one
        # pointer only, never recursively follow another pointer or include.
        common = directory / "commondir"
        if os.path.lexists(common):
            text = _read_regular(common, MAX_POINTER_BYTES)
            if text is None:
                return None
            directory = _pointer(directory, text)
            if directory is None or directory.is_symlink() or not directory.is_dir():
                return None
        return directory
    except (OSError, ValueError):
        return None


def _safe_remote(value: str) -> str | None:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    if not value or len(value) > MAX_REMOTE_CHARS or "\\" in value:
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    if "://" not in value:
        match = _SCP_REMOTE.fullmatch(value)
        if match is None or "@" in match["path"] or match["path"].startswith(":"):
            return None
        value = "ssh://" + match["host"] + "/" + match["path"]
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "ssh", "git"} or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        port = parsed.port
        if ":" in host:
            host = "[" + host + "]"
        if port is not None:
            host += ":" + str(port)
        if not parsed.path.strip("/"):
            return None
        # Userinfo and URL options are not repository identity. Never send
        # tokens embedded in HTTPS credentials, query strings or fragments.
        result = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        decoded = unquote(result)
        if any(character.isspace() or ord(character) < 32 for character in decoded):
            return None
        if contains_sensitive_input(decoded):
            return None
        return result
    except ValueError:
        return None


def local_project_hints(cwd: str) -> list[str]:
    """Return at most one sanitized origin from the nearest repository boundary."""
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or len(cwd) > 4096:
        return []
    directory = Path(os.path.normpath(cwd))
    try:
        for _ in range(MAX_PARENT_LEVELS):
            marker = directory / ".git"
            if os.path.lexists(marker):
                git_dir = _git_directory(marker)
                if git_dir is None:
                    return []
                text = _read_regular(git_dir / "config", MAX_CONFIG_BYTES)
                if text is None or "\x00" in text:
                    return []
                # Git has no inherited DEFAULT section; a NUL section cannot
                # exist in the already validated input.
                config = configparser.ConfigParser(
                    interpolation=None, strict=True, default_section="\x00"
                )
                config.read_string(text)
                remote = config.get('remote "origin"', "url", fallback="")
                safe = _safe_remote(remote)
                return [safe] if safe else []
            if directory == directory.parent:
                break
            directory = directory.parent
    except (OSError, ValueError, configparser.Error):
        return []
    return []
