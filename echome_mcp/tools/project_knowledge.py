"""MCP tools for project constraints, artifacts, and impact analysis."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from echome_mcp.hub_client import MCPHubClient

IGNORED_PARTS = {".git", ".venv", "__pycache__", "data", "dist", "node_modules", "build", ".cache"}
INDEX_EXTENSIONS = {".md", ".txt", ".py", ".ts", ".vue", ".yaml", ".yml", ".json"}
MAX_ARTIFACT_BYTES = 2_000_000
CODE_EXTENSIONS = {".py", ".ts", ".vue"}
SENSITIVE_SUFFIXES = {".cer", ".cert", ".crt", ".der", ".jks", ".key", ".p12", ".pem", ".pfx"}
SENSITIVE_NAME_PATTERN = re.compile(
    r"(?:^|[._-])(credentials?|secrets?|tokens?|service[-_]account)(?:[._-]|$)"
)
PRIVATE_MATERIAL_MARKERS = (
    "-----BEGIN " "PRIVATE KEY-----",
    "-----BEGIN " "ENCRYPTED PRIVATE KEY-----",
    "-----BEGIN " "RSA PRIVATE KEY-----",
    "-----BEGIN " "DSA PRIVATE KEY-----",
    "-----BEGIN " "OPENSSH PRIVATE KEY-----",
    "-----BEGIN " "EC PRIVATE KEY-----",
    "-----BEGIN " "CERTIFICATE-----",
)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _artifact_kind(path: Path) -> str:
    path_text = path.as_posix().lower()
    if "test" in path.parts or path.name.startswith("test_") or path.name.endswith(".test.ts"):
        return "test"
    if path.suffix in {".py", ".ts", ".vue"}:
        return "code"
    if "design" in path_text or "architecture" in path_text:
        return "design"
    if "requirement" in path_text or "spec" in path_text:
        return "requirement"
    return "document"


def _is_sensitive_artifact(path: Path, content: str) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == ".env" or name.startswith(".env.") or name.endswith(".env") or ".env." in name:
        return True
    if suffix in SENSITIVE_SUFFIXES:
        return True
    if suffix not in CODE_EXTENSIONS and SENSITIVE_NAME_PATTERN.search(name):
        return True
    return any(marker in content for marker in PRIVATE_MATERIAL_MARKERS)


def _scan_artifacts(root: Path, max_files: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    manifests: list[dict[str, Any]] = []
    contents: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if len(manifests) >= max_files:
            break
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_relative_to(root):
            continue
        if not resolved.is_file() or path.suffix.lower() not in INDEX_EXTENSIONS:
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS or part.startswith(".") for part in relative.parts):
            continue
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _is_sensitive_artifact(relative, content):
            continue
        raw = content.encode("utf-8")
        logical_path = relative.as_posix()
        manifests.append(
            {
                "logical_path": logical_path,
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "kind": _artifact_kind(relative),
                "title": path.stem.replace("-", " ").replace("_", " "),
                "source_uri": path.as_uri(),
                "metadata": {"source": "local_index"},
            }
        )
        contents[logical_path] = content
    return manifests, contents


async def echome_project_context(
    project_id: str,
    task: str,
    changed_paths: list[str] | None = None,
    limit: int = 20,
    mode: str = "local",
    token_budget: int = 6000,
    as_of: str | None = None,
    valid_at: str | None = None,
    record_run: bool = True,
    shadow: bool = False,
    policy_mode: str = "shadow",
) -> str:
    """Return one AI-readable project context pack across memory and constraints."""
    client = MCPHubClient()
    result = await client.project_context(
        project_id,
        task,
        changed_paths,
        limit,
        mode,
        token_budget,
        as_of,
        valid_at,
        record_run,
        shadow,
        policy_mode,
    )
    return _json(result)


async def echome_reflect_prepare(
    project_id: str,
    query: str,
    changed_paths: list[str] | None = None,
    limit: int = 30,
    token_budget: int = 12_000,
    supersedes_id: str | None = None,
) -> str:
    """Prepare all server-owned evidence needed for a client-generated reflection."""
    client = MCPHubClient()
    result = await client.prepare_reflection(
        {
            "project_id": project_id,
            "query": query,
            "changed_paths": changed_paths or [],
            "limit": limit,
            "token_budget": token_budget,
            "supersedes_id": supersedes_id,
        }
    )
    return _json(result)


async def echome_reflect_submit(
    project_id: str,
    query: str,
    claims: list[dict[str, Any]],
    source_watermark: dict[str, Any],
    idempotency_key: str,
    kind: str = "mental_model",
    supersedes_id: str | None = None,
) -> str:
    """Persist a derived view after the Hub revalidates sources and claim citations."""
    client = MCPHubClient()
    result = await client.submit_reflection(
        {
            "project_id": project_id,
            "kind": kind,
            "query": query,
            "claims": claims,
            "source_watermark": source_watermark,
            "idempotency_key": idempotency_key,
            "supersedes_id": supersedes_id,
        }
    )
    return _json(result)


async def echome_project_impact(
    project_id: str,
    change: str,
    changed_paths: list[str] | None = None,
    constraint_ids: list[str] | None = None,
    depth: int = 2,
    limit: int = 20,
) -> str:
    """Return impacted constraints and evidence for a proposed change."""
    client = MCPHubClient()
    result = await client.project_impact(
        project_id, change, changed_paths, constraint_ids, depth, limit
    )
    return _json(result)


async def echome_project_index(
    project_id: str,
    root_path: str,
    dry_run: bool = True,
    max_files: int = 500,
) -> str:
    """Hash local project artifacts and upload only revisions missing from Hub."""
    root = Path(root_path).expanduser().resolve()
    if not root.is_dir():
        return f"Project root does not exist or is not a directory: {root}"
    client = MCPHubClient()
    project = await client.get_project(project_id)
    if project is None:
        return f"Project not found: {project_id}"
    path_patterns = [
        pattern.strip()
        for pattern in (project.get("path_patterns") or [])
        if isinstance(pattern, str) and pattern.strip()
    ]
    if not path_patterns:
        return "Project path_patterns is empty; refusing to index local files."
    if not _root_is_allowed(root, path_patterns):
        return "Root path is outside the project's configured path_patterns."
    manifests, contents = _scan_artifacts(root, max_files=max_files)
    check = await client.check_artifact_sync(project_id, manifests)
    if dry_run:
        return _json({"dry_run": True, "scanned": len(manifests), **check})
    needed = set(check.get("needed", []))
    uploads = [
        {**item, "content": contents[item["logical_path"]]}
        for item in manifests
        if item["logical_path"] in needed
    ]
    applied = {"created": [], "unchanged": []}
    for start in range(0, len(uploads), 50):
        batch = await client.apply_artifact_sync(project_id, uploads[start : start + 50])
        applied["created"].extend(batch.get("created", []))
        applied["unchanged"].extend(batch.get("unchanged", []))
    return _json(
        {
            "dry_run": False,
            "scanned": len(manifests),
            "uploaded": len(applied["created"]),
            "saved_bytes": check.get("saved_bytes", 0),
            "remote_only": check.get("remote_only", []),
            "result": applied,
        }
    )


def _root_is_allowed(root: Path, path_patterns: list[str]) -> bool:
    for pattern in path_patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        expanded = Path(pattern).expanduser().resolve()
        pattern_text = str(expanded)
        if any(wildcard in pattern_text for wildcard in "*?["):
            candidates = (root, *root.parents)
            if any(candidate.match(pattern_text) for candidate in candidates):
                return True
            continue
        if root == expanded or root.is_relative_to(expanded):
            return True
    return False


async def echome_constraint_propose(
    project_id: str,
    title: str,
    statement: str,
    rationale: str | None = None,
    kind: str = "architecture",
    stability: str = "evolving",
    confidence: float = 0.7,
    tags: list[str] | None = None,
) -> str:
    """Create an AI-proposed project constraint without changing memory behavior."""
    client = MCPHubClient()
    result = await client.create_constraint(
        {
            "project_id": project_id,
            "title": title,
            "statement": statement,
            "rationale": rationale,
            "kind": kind,
            "status": "proposed",
            "stability": stability,
            "confidence": confidence,
            "source": "ai",
            "tags": tags or [],
        }
    )
    return _json(result)


async def echome_project_event_append(
    project_id: str,
    event_type: str,
    title: str,
    content: str,
    occurred_at: str | None = None,
    source: str = "ai_client",
    source_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    links: list[dict[str, Any]] | None = None,
) -> str:
    """Append a structured project event without promoting it to an active constraint."""
    client = MCPHubClient()
    result = await client.append_project_event(
        {
            "project_id": project_id,
            "event_type": event_type,
            "title": title,
            "content": content,
            "occurred_at": occurred_at,
            "source": source,
            "source_ref": source_ref,
            "metadata": metadata or {},
            "idempotency_key": idempotency_key,
            "links": links or [],
        }
    )
    return _json(result)


async def echome_project_preflight(
    project_id: str,
    task: str,
    changed_paths: list[str] | None = None,
    planned_actions: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Return read-only, evidence-backed project warnings and validation requirements."""
    client = MCPHubClient()
    result = await client.project_preflight(
        project_id,
        task,
        changed_paths,
        planned_actions,
        limit,
    )
    return _json(result)
