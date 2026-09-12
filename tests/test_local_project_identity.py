"""Caller repository paths must not be confused with the MCP host directory."""

import asyncio
import subprocess
from unittest.mock import AsyncMock

import pytest

from echome_mcp import runtime


@pytest.mark.parametrize("component", ["api", "web"])
def test_explicit_path_adds_its_own_git_remote_and_root(tmp_path, monkeypatch, component):
    repository = tmp_path / "okb" / component
    repository.mkdir(parents=True)
    nested = repository / "src"
    nested.mkdir()
    remote = f"https://example.com/okbox/{component}.git"
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "remote", "add", "origin", remote], check=True)
    captured = {}

    class Client:
        cache_namespace = "test"
        cache_enabled = False

        async def unified_context(self, payload):
            captured.update(payload)
            return {"runtime": {"degraded": False}}

    monkeypatch.setattr(runtime, "MCPHubClient", Client)
    asyncio.run(runtime.echome_context("inspect repository", project_hint=str(nested)))

    assert captured["project_hint"] == str(nested)
    assert captured["project_hints"] == [remote, str(repository)]


@pytest.mark.parametrize("hint", ["OKB", "/missing/okb/api", "git@example.com:okbox/api.git"])
def test_nonlocal_identity_never_uses_host_cwd(monkeypatch, hint):
    local_hints = AsyncMock()

    class Client:
        cache_namespace = "test"
        cache_enabled = False

        async def unified_context(self, payload):
            return {"runtime": {"degraded": False}}

    monkeypatch.setattr(runtime, "MCPHubClient", Client)
    monkeypatch.setattr(runtime, "_local_project_hints", local_hints)
    asyncio.run(runtime.echome_context("inspect repository", project_hint=hint))
    local_hints.assert_not_awaited()
