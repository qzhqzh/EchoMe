"""Tests for local project artifact indexing."""

import asyncio
import hashlib
import json

import pytest

from echome_mcp.tools import project_knowledge
from echome_mcp.tools.project_knowledge import _scan_artifacts


class _FakeClient:
    def __init__(self, project: dict) -> None:
        self.project = project
        self.check_calls: list[tuple[str, list[dict]]] = []

    async def get_project(self, project_id: str) -> dict:
        return self.project

    async def check_artifact_sync(self, project_id: str, artifacts: list[dict]) -> dict:
        self.check_calls.append((project_id, artifacts))
        return {"needed": [], "unchanged": [], "remote_only": [], "saved_bytes": 0}


def _fake_client(monkeypatch: pytest.MonkeyPatch, project: dict) -> _FakeClient:
    client = _FakeClient(project)
    monkeypatch.setattr(project_knowledge, "MCPHubClient", lambda: client)
    return client


def test_scan_artifacts_hashes_text_and_excludes_dependencies(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "architecture.md"
    source.write_text("# Architecture\n\nHub and MCP.", encoding="utf-8")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "package.json").write_text("{}", encoding="utf-8")

    manifests, contents = _scan_artifacts(tmp_path, max_files=20)

    assert [item["logical_path"] for item in manifests] == ["docs/architecture.md"]
    assert manifests[0]["kind"] == "design"
    assert manifests[0]["content_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert contents["docs/architecture.md"].startswith("# Architecture")


def test_scan_artifacts_excludes_sensitive_files_but_keeps_auth_token_source(tmp_path) -> None:
    (tmp_path / "auth_token.py").write_text("TOKEN_NAME = 'demo'", encoding="utf-8")
    (tmp_path / "token_service.ts").write_text("export const token = true", encoding="utf-8")
    (tmp_path / "credentials.json").write_text('{"password": "secret"}', encoding="utf-8")
    (tmp_path / "secrets.yaml").write_text("api_key: secret", encoding="utf-8")
    (tmp_path / "access_token.txt").write_text("secret-token", encoding="utf-8")
    (tmp_path / ".env").write_text("PASSWORD=secret", encoding="utf-8")
    (tmp_path / ".env.local").write_text("PASSWORD=secret", encoding="utf-8")
    (tmp_path / "settings.env").write_text("PASSWORD=secret", encoding="utf-8")
    (tmp_path / "private_material.txt").write_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----", encoding="utf-8"
    )

    manifests, contents = _scan_artifacts(tmp_path, max_files=20)

    logical_paths = {item["logical_path"] for item in manifests}
    assert {"auth_token.py", "token_service.ts"} <= logical_paths
    assert (
        not {
            "credentials.json",
            "secrets.yaml",
            "access_token.txt",
            ".env",
            ".env.local",
            "settings.env",
            "private_material.txt",
        }
        & logical_paths
    )
    assert "credentials.json" not in contents


def test_scan_artifacts_does_not_follow_file_symlink_outside_root(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside project", encoding="utf-8")
    (root / "linked.md").symlink_to(outside)

    manifests, contents = _scan_artifacts(root, max_files=20)

    assert manifests == []
    assert contents == {}


def test_project_index_rejects_empty_path_allowlist(tmp_path, monkeypatch) -> None:
    client = _fake_client(monkeypatch, {"path_patterns": []})

    result = asyncio.run(project_knowledge.echome_project_index("demo", str(tmp_path)))

    assert result == "Project path_patterns is empty; refusing to index local files."
    assert client.check_calls == []


def test_project_index_rejects_root_outside_path_allowlist(tmp_path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    client = _fake_client(monkeypatch, {"path_patterns": [str(allowed)]})

    result = asyncio.run(project_knowledge.echome_project_index("demo", str(outside)))

    assert result == "Root path is outside the project's configured path_patterns."
    assert client.check_calls == []


def test_project_index_calls_check_for_allowed_root(tmp_path, monkeypatch) -> None:
    source = tmp_path / "main.py"
    source.write_text("print('ok')", encoding="utf-8")
    client = _fake_client(monkeypatch, {"path_patterns": [str(tmp_path)]})

    result = asyncio.run(project_knowledge.echome_project_index("demo", str(tmp_path)))

    payload = json.loads(result)
    assert payload["dry_run"] is True
    assert payload["scanned"] == 1
    assert len(client.check_calls) == 1
    assert client.check_calls[0][0] == "demo"
    assert client.check_calls[0][1][0]["logical_path"] == "main.py"
