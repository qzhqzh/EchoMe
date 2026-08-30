"""High-confidence server-side rejection of credentials and private key material."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException

PRIVATE_KEY_MARKERS = (
    "-----BEGIN " "PRIVATE KEY-----",
    "-----BEGIN " "ENCRYPTED PRIVATE KEY-----",
    "-----BEGIN " "RSA PRIVATE KEY-----",
    "-----BEGIN " "DSA PRIVATE KEY-----",
    "-----BEGIN " "OPENSSH PRIVATE KEY-----",
    "-----BEGIN " "EC PRIVATE KEY-----",
)
TOKEN_PATTERNS = (
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe_live_key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{16,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)
BEARER_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:authorization\s*:\s*)?bearer\s+([A-Za-z0-9._~+/-]{16,}={0,2})"
)
ASSIGNMENT_PATTERN = re.compile(
    r"(?im)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|secret[_-]?key|password|passwd|credential)\b[\"']?\s*[:=]\s*"
    r"[\"']?([^\s\"',;}{]{8,})"
)
URL_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]{8,})@[^\s/]+"
)
PLACEHOLDER_MARKERS = (
    "example",
    "sample",
    "placeholder",
    "dummy",
    "fake",
    "redacted",
    "changeme",
    "not-a-real",
    "not_real",
    "dev-token",
    "test-secret",
    "test_token",
    "test-token",
    "your_",
    "your-",
    "<",
    "${",
    "{{",
    "***",
    "xxx",
)
SENSITIVE_SUFFIXES = {".cer", ".crt", ".der", ".jks", ".key", ".p12", ".pem", ".pfx"}


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def _entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_secret(value: str) -> bool:
    normalized = value.strip().strip("\"'")
    if len(normalized) < 12 or _is_placeholder(normalized):
        return False
    classes = sum(
        any(check(char) for char in normalized)
        for check in (str.islower, str.isupper, str.isdigit, lambda char: not char.isalnum())
    )
    return classes >= 3 or (len(normalized) >= 16 and _entropy(normalized) >= 3.2)


def find_sensitive_content(text: str) -> list[dict[str, Any]]:
    """Return finding metadata without ever echoing the matched credential value."""
    findings: list[dict[str, Any]] = []
    for marker in PRIVATE_KEY_MARKERS:
        offset = text.find(marker)
        if offset >= 0:
            findings.append({"kind": "private_key", "line": _line_number(text, offset)})
    for kind, pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_placeholder(match.group(0)):
                findings.append({"kind": kind, "line": _line_number(text, match.start())})
    for match in BEARER_TOKEN_PATTERN.finditer(text):
        if not _is_placeholder(match.group(1)):
            findings.append(
                {"kind": "bearer_token", "line": _line_number(text, match.start())}
            )
    for match in ASSIGNMENT_PATTERN.finditer(text):
        if _looks_like_secret(match.group(1)):
            findings.append(
                {"kind": "credential_assignment", "line": _line_number(text, match.start())}
            )
    for match in URL_CREDENTIAL_PATTERN.finditer(text):
        if _looks_like_secret(match.group(1)):
            findings.append({"kind": "url_credential", "line": _line_number(text, match.start())})
    unique = {(str(item["kind"]), item["line"]) for item in findings}
    return [
        {"kind": kind, "line": line}
        for kind, line in sorted(unique, key=lambda item: (item[1] or 0, item[0]))
    ]


def _sensitive_path_finding(logical_path: str) -> dict[str, Any] | None:
    path = PurePosixPath(logical_path.lower())
    name = path.name
    if name == ".env" or (
        name.startswith(".env.")
        and not name.endswith((".example", ".sample", ".template"))
    ):
        return {"kind": "sensitive_artifact_path", "line": None}
    if path.suffix in SENSITIVE_SUFFIXES:
        return {"kind": "private_material_path", "line": None}
    return None


def find_sensitive_artifact(
    logical_path: str,
    content: str,
    *metadata: str | None,
) -> list[dict[str, Any]]:
    """Inspect an artifact without returning any matched credential values."""
    findings = find_sensitive_content(content)
    path_finding = _sensitive_path_finding(logical_path)
    if path_finding:
        findings.append(path_finding)
    for value in metadata:
        if value:
            findings.extend(find_sensitive_content(value))
    unique = {(str(item["kind"]), item["line"]) for item in findings}
    return [
        {"kind": kind, "line": line}
        for kind, line in sorted(unique, key=lambda item: (item[1] or 0, item[0]))
    ]


def _reject(findings: list[dict[str, Any]]) -> None:
    if not findings:
        return
    raise HTTPException(
        status_code=422,
        detail={
            "code": "sensitive_content_rejected",
            "message": "Potential credential or private key material cannot be stored.",
            "findings": findings,
        },
    )


def require_safe_content(*values: str | None) -> None:
    """Reject high-confidence secrets from any server-side write path."""
    findings: list[dict[str, Any]] = []
    for value in values:
        if value:
            findings.extend(find_sensitive_content(value))
    _reject(findings)


def require_safe_artifact(logical_path: str, content: str, *metadata: str | None) -> None:
    """Reject secret-bearing artifact paths or content before indexing."""
    _reject(find_sensitive_artifact(logical_path, content, *metadata))
