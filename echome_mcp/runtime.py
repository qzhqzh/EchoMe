"""Unified MCP context routing, structured errors, and read-only cache fallback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import stat
import uuid
from contextlib import suppress
from pathlib import Path
from time import time
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from echome_mcp import __version__
from echome_mcp.hub_client import MCPHubClient

ERROR_SCHEMA_VERSION = "echome.error.v1"
CONTEXT_SCHEMA_VERSION = "echome.context.v1"
CACHE_SCHEMA_VERSION = 2
DEFAULT_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _cache_directory() -> Path:
    configured = os.getenv("ECHOME_CONTEXT_CACHE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".echome" / "cache" / "context"


def _cache_encryption_key() -> bytes | None:
    """Load or create a local random key without deriving it from Hub credentials."""
    directory = _cache_directory()
    key_path = directory / ".key"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = directory.lstat()
        if not stat.S_ISDIR(directory_stat.st_mode) or directory.is_symlink():
            return None
        directory.chmod(0o700)
        try:
            key_stat = key_path.lstat()
            if not stat.S_ISREG(key_stat.st_mode) or key_path.is_symlink():
                return None
            key_path.chmod(0o600)
            key = key_path.read_bytes()
        except FileNotFoundError:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(key_path, flags, 0o600)
            try:
                key = os.urandom(32)
                os.write(descriptor, key)
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)
        return key if len(key) == 32 else None
    except OSError:
        return None


def _cache_key(payload: dict[str, Any], namespace: str) -> str:
    stable = {
        key: value
        for key, value in payload.items()
        if key not in {"request_id", "client", "client_version"}
    }
    encoded = json.dumps(
        {
            "namespace": namespace,
            "context_schema_version": CONTEXT_SCHEMA_VERSION,
            "request": stable,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _cache_max_age_seconds() -> int:
    with suppress(ValueError):
        return max(0, int(os.getenv("ECHOME_CONTEXT_CACHE_MAX_AGE_SECONDS", "")))
    return DEFAULT_CACHE_MAX_AGE_SECONDS


def _write_cache(
    payload: dict[str, Any],
    context: dict[str, Any],
    namespace: str,
    encryption_key: bytes | None,
) -> None:
    if encryption_key is None:
        return
    directory = _cache_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache_id = _cache_key(payload, namespace)
    path = directory / f"{cache_id}.json"
    temporary = path.with_suffix(".tmp")
    created_at = int(time())
    plaintext = json.dumps(
        {"created_at": created_at, "context": context}, ensure_ascii=False
    ).encode()
    nonce = os.urandom(12)
    ciphertext = AESGCM(encryption_key).encrypt(
        nonce,
        plaintext,
        f"{CONTEXT_SCHEMA_VERSION}\0{cache_id}".encode(),
    )
    temporary.write_text(
        json.dumps(
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            }
        ),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _read_cache(
    payload: dict[str, Any],
    namespace: str,
    encryption_key: bytes | None,
) -> dict[str, Any] | None:
    if encryption_key is None:
        return None
    cache_id = _cache_key(payload, namespace)
    path = _cache_directory() / f"{cache_id}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("schema_version") != CACHE_SCHEMA_VERSION:
            return None
        plaintext = AESGCM(encryption_key).decrypt(
            base64.b64decode(cached["nonce"]),
            base64.b64decode(cached["ciphertext"]),
            f"{CONTEXT_SCHEMA_VERSION}\0{cache_id}".encode(),
        )
        decrypted = json.loads(plaintext)
        created_at = int(decrypted["created_at"])
        age = int(time()) - created_at
        if age < 0 or age > _cache_max_age_seconds():
            return None
        context = decrypted["context"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError, InvalidTag):
        return None
    return context if isinstance(context, dict) else None


def error_contract(exc: Exception, request_id: str | None = None) -> dict[str, Any]:
    """Classify runtime failures without relying on possibly empty exception text."""
    code = "INTERNAL_ERROR"
    message = str(exc).strip() or exc.__class__.__name__
    retryable = False
    degraded = False
    action = "Inspect the EchoMe runtime logs."
    if isinstance(exc, httpx.TimeoutException):
        code = "HUB_TIMEOUT"
        message = "EchoMe Hub request timed out"
        retryable = degraded = True
        action = "Retry or use cached read-only context."
    elif isinstance(exc, httpx.NetworkError):
        code = "HUB_UNAVAILABLE"
        message = "EchoMe Hub is unreachable"
        retryable = degraded = True
        action = "Use cached read-only context or run echome_runtime_health."
    elif isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        code = {
            401: "AUTH_FAILED",
            403: "AUTH_FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "INVALID_REQUEST",
            429: "RATE_LIMITED",
        }.get(status, "HUB_ERROR")
        retryable = status == 429 or status >= 500
        degraded = status >= 500
        try:
            response_payload = exc.response.json()
            detail = response_payload.get("detail")
            if not detail and isinstance(response_payload.get("error"), dict):
                detail = response_payload["error"].get("message")
            if detail:
                message = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        except (ValueError, AttributeError):
            pass
        action = "Check the request and EchoMe authentication." if status < 500 else "Retry later."
    return {
        "schema_version": ERROR_SCHEMA_VERSION,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id or str(uuid.uuid4()),
            "degraded": degraded,
            "suggested_action": action,
        },
    }


async def _local_project_hint() -> str | None:
    """Read the current Git remote or repository root without mutating it."""
    commands = [
        ("config", "--get", "remote.origin.url"),
        ("rev-parse", "--show-toplevel"),
    ]
    for arguments in commands:
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=2)
        except (OSError, TimeoutError):
            return None
        value = stdout.decode().strip()
        if value:
            return value
    return None


async def echome_context(
    task: str,
    project_hint: str | None = None,
    changed_paths: list[str] | None = None,
    mode: str = "auto",
    token_budget: int = 6000,
    limit: int = 20,
    as_of: str | None = None,
    valid_at: str | None = None,
    client: str | None = None,
    client_version: str | None = None,
) -> str:
    """Call the unified Hub route and degrade only to an exact last-known-good read."""
    request_id = str(uuid.uuid4())
    inferred_hint = project_hint
    if inferred_hint is None and mode != "personal":
        inferred_hint = await _local_project_hint()
    payload: dict[str, Any] = {
        "task": task,
        "project_hint": inferred_hint,
        "changed_paths": changed_paths or [],
        "mode": mode,
        "token_budget": token_budget,
        "limit": limit,
        "as_of": as_of,
        "valid_at": valid_at,
        "record_run": True,
        "request_id": request_id,
        "client": client or "mcp",
        "client_version": client_version or __version__,
    }
    client_instance = MCPHubClient()
    cache_namespace = client_instance.cache_namespace
    cache_encryption_key = _cache_encryption_key() if client_instance.cache_enabled else None
    try:
        context = await client_instance.unified_context(payload)
    except Exception as exc:
        failure = error_contract(exc, request_id)
        cached = (
            _read_cache(payload, cache_namespace, cache_encryption_key)
            if failure["error"]["degraded"]
            else None
        )
        if cached is not None:
            runtime = cached.setdefault("runtime", {})
            runtime.update(
                {
                    "request_id": request_id,
                    "degraded": True,
                    "fallback": "last_known_good",
                }
            )
            cached["degradation_error"] = failure["error"]
            return json.dumps(cached, ensure_ascii=False, indent=2)
        return json.dumps(failure, ensure_ascii=False, indent=2)
    with suppress(OSError, TypeError):
        _write_cache(payload, context, cache_namespace, cache_encryption_key)
    return json.dumps(context, ensure_ascii=False, indent=2)


async def echome_runtime_health() -> str:
    """Report MCP/cache configuration and authenticated Hub component health."""
    request_id = str(uuid.uuid4())
    try:
        hub = await MCPHubClient().runtime_health()
    except Exception as exc:
        return json.dumps(error_contract(exc, request_id), ensure_ascii=False, indent=2)
    payload = {
        **hub,
        "mcp_version": __version__,
        "profile": os.getenv("ECHOME_MCP_PROFILE", "full"),
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "error_schema_version": ERROR_SCHEMA_VERSION,
        "cache": {
            "mode": "read_only_last_known_good",
            "directory": str(_cache_directory()),
            "encryption": "aes-256-gcm-local-random-key",
            "enabled": MCPHubClient().cache_enabled,
            "key_source": "local_random_file",
            "max_age_seconds": _cache_max_age_seconds(),
        },
        "request_id": request_id,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def echome_context_outcome(
    context_run_id: str,
    outcome: str,
    idempotency_key: str,
    reported_by: str = "ai",
    source: str = "mcp",
    project_event_id: str | None = None,
    note: str | None = None,
) -> str:
    """Append explicit evidence about whether a delivered context helped."""
    payload = {
        "context_run_id": context_run_id,
        "outcome": outcome,
        "reported_by": reported_by,
        "source": source,
        "project_event_id": project_event_id,
        "note": note,
        "idempotency_key": idempotency_key,
    }
    result = await MCPHubClient().create_context_outcome(payload)
    return json.dumps(result, ensure_ascii=False, indent=2)
