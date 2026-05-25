"""echome doctor - Diagnose EchoMe CLI environment and configuration."""

import json
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from echome import __version__
from echome.core.config import CONFIG_FILE, ECHOME_DIR, VAULT_DIR, Config

console = Console()

GITHUB_RELEASES_URL = "https://api.github.com/repos/qzhqzh/EchoMe/releases/latest"
VERSION_CACHE_FILE = ECHOME_DIR / ".state" / "version_cache.json"


class CheckResult:
    """Result of a single check."""

    def __init__(self, name: str, status: str, detail: str = ""):
        self.name = name
        self.status = status  # "ok", "warn", "fail"
        self.detail = detail

    def __str__(self) -> str:
        icon = {"ok": "✓", "warn": "⚠", "fail": "✗"}[self.status]
        color = {"ok": "green", "warn": "yellow", "fail": "red"}[self.status]
        line = f"  [{color}]{icon}[/{color}] {self.name}"
        if self.detail:
            line += f"  [dim]{self.detail}[/dim]"
        return line


def _detect_install_source() -> str:
    """Detect how echome was installed: 'editable', 'github', or 'pypi'."""
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("echome")
        direct_url = dist.read_text("direct_url.json")
        if direct_url and '"dir_info"' in direct_url:
            return "editable"
        if "github" in (direct_url or ""):
            return "github"
        if direct_url and "pypi.org" in direct_url:
            return "pypi"
    except Exception:
        pass
    return "unknown"


def _check_environment() -> list[CheckResult]:
    """Check version and install source."""
    results = []

    # Version
    results.append(CheckResult("version", "ok", f"v{__version__}"))

    # Install source
    source = _detect_install_source()
    results.append(CheckResult("install", "ok", source))

    return results


def _check_vault() -> list[CheckResult]:
    """Check vault directory and files."""
    results = []

    # Vault dir
    if ECHOME_DIR.exists():
        results.append(CheckResult("vault_dir", "ok", str(ECHOME_DIR)))
    else:
        results.append(CheckResult("vault_dir", "fail", "run `echome init`"))

    # Vault files
    if VAULT_DIR.exists():
        memory_files = list(VAULT_DIR.glob("**/*.md"))
        count = len(memory_files)
        results.append(CheckResult("memories", "ok", f"{count} files"))
    else:
        results.append(CheckResult("memories", "fail", "vault not initialized"))

    return results


def _check_config() -> list[CheckResult]:
    """Check configuration file and values."""
    results = []

    # Config file
    if CONFIG_FILE.exists():
        try:
            Config.load()
            results.append(CheckResult("config_file", "ok", str(CONFIG_FILE)))
        except Exception as e:
            results.append(CheckResult("config_file", "fail", f"parse error: {e}"))
    else:
        results.append(CheckResult("config_file", "fail", "run `echome init`"))

    # Hub URL
    config = Config.load()
    if config.hub_url:
        results.append(CheckResult("hub_url", "ok", config.hub_url))
    else:
        results.append(CheckResult("hub_url", "fail", "not configured"))

    # Token
    if config.token:
        results.append(CheckResult("token", "ok", "configured (hidden)"))
    else:
        results.append(CheckResult("token", "warn", "not set — Hub features unavailable"))

    return results


def _check_hub_connection() -> list[CheckResult]:
    """Check Hub connectivity."""
    results = []
    config = Config.load()

    if not config.token:
        results.append(CheckResult("health", "warn", "no token — skip"))
        return results

    try:
        from echome.core.client import HubClient

        client = HubClient(config)
        health = client.health()
        hub_version = health.get("version", "?")
        results.append(CheckResult("health", "ok", f"connected (Hub v{hub_version})"))
    except Exception as e:
        results.append(CheckResult("health", "fail", str(e)))

    return results


def _check_mcp() -> list[CheckResult]:
    """Check MCP registration in Claude and Codex."""
    results = []

    # Claude MCP
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            data = json.loads(claude_json.read_text())
            if "echome" in data.get("mcpServers", {}):
                results.append(CheckResult("claude_mcp", "ok", str(claude_json)))
            else:
                results.append(CheckResult("claude_mcp", "warn", "not registered"))
        except Exception:
            results.append(CheckResult("claude_mcp", "fail", "parse error"))
    else:
        results.append(CheckResult("claude_mcp", "warn", "not registered"))

    # Codex MCP
    codex_toml = Path.home() / ".codex" / "config.toml"
    codex_json = Path.home() / ".codex" / "mcp.json"

    if codex_toml.exists():
        try:
            content = codex_toml.read_text()
            if "[mcp_servers.echome]" in content:
                results.append(CheckResult("codex_mcp", "ok", str(codex_toml)))
            else:
                results.append(CheckResult("codex_mcp", "warn", "not registered"))
        except Exception:
            results.append(CheckResult("codex_mcp", "fail", "read error"))
    elif codex_json.exists():
        try:
            data = json.loads(codex_json.read_text())
            if "echome" in data.get("mcpServers", {}):
                results.append(CheckResult("codex_mcp", "ok", str(codex_json)))
            else:
                results.append(CheckResult("codex_mcp", "warn", "not registered"))
        except Exception:
            results.append(CheckResult("codex_mcp", "fail", "parse error"))
    else:
        results.append(CheckResult("codex_mcp", "warn", "not registered"))

    return results


def _fetch_latest_version() -> str | None:
    """Fetch latest version from GitHub releases API."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--connect-timeout", "5", GITHUB_RELEASES_URL],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("tag_name", "").lstrip("v")
    except Exception:
        pass
    return None


def _check_updates() -> list[CheckResult]:
    """Check for updates."""
    results = []

    # Local version
    results.append(CheckResult("local_version", "ok", f"v{__version__}"))

    # Remote version
    remote = _fetch_latest_version()
    if remote:
        if remote == __version__:
            results.append(CheckResult("remote_version", "ok", f"v{remote} (current)"))
        else:
            results.append(
                CheckResult("updates", "warn", f"v{remote} available → run `echome update`")
            )
    else:
        results.append(CheckResult("remote_version", "warn", "fetch failed"))

    return results


def doctor() -> None:
    """Diagnose EchoMe environment: version, vault, config, Hub, MCP, updates."""
    console.print(f"\n[bold]EchoMe Doctor[/bold] v{__version__} · linux\n")

    all_results: list[CheckResult] = []
    ok_count = 0
    warn_count = 0
    fail_count = 0

    checks = [
        ("Environment", _check_environment),
        ("Vault", _check_vault),
        ("Configuration", _check_config),
        ("Hub Connection", _check_hub_connection),
        ("MCP", _check_mcp),
        ("Updates", _check_updates),
    ]

    for section_name, check_func in checks:
        results = check_func()
        if not results:
            continue

        console.print(f"[bold]{section_name}[/bold]")
        for r in results:
            console.print(str(r))
            all_results.append(r)
            if r.status == "ok":
                ok_count += 1
            elif r.status == "warn":
                warn_count += 1
            else:
                fail_count += 1
        console.print()

    # Summary
    console.print("─" * 50)
    summary = f"{ok_count} ok · {warn_count} warn · {fail_count} fail"
    if fail_count > 0:
        console.print(f"[red]{summary}[/red]")
    elif warn_count > 0:
        console.print(f"[yellow]{summary}[/yellow]")
    else:
        console.print(f"[green]{summary}[/green]")
    console.print()


if __name__ == "__main__":
    typer.run(doctor)
