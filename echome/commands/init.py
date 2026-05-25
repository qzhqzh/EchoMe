"""echome init - Initialize local vault, configure Hub, and optionally set up MCP."""

import re

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from echome.core.config import Config, ensure_vault_dirs

console = Console()


def _mcp_available() -> bool:
    """Check if MCP server package is installed."""
    try:
        import echome_mcp  # noqa: F401
        return True
    except ImportError:
        return False


def _setup_claude_mcp_fallback() -> None:
    """Fallback: write Claude MCP config directly to ~/.claude.json."""
    import json
    from pathlib import Path

    claude_config = Path.home() / ".claude.json"
    mcp_config = {
        "type": "stdio",
        "command": "echome",
        "args": ["mcp", "serve"],
        "env": {},
    }

    try:
        data = json.loads(claude_config.read_text()) if claude_config.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    # Add to user-level mcpServers (available in all projects)
    data.setdefault("mcpServers", {})["echome"] = mcp_config
    claude_config.write_text(json.dumps(data, indent=2))


def _setup_mcp() -> None:
    """Register EchoMe MCP server in Claude Code and Codex CLI."""
    import json
    import subprocess
    from pathlib import Path

    mcp_config = {
        "type": "stdio",
        "command": "echome",
        "args": ["mcp", "serve"],
        "env": {},
    }

    registered = []

    # Claude Code - use official CLI command for correct configuration
    try:
        # User scope makes echome available across all projects
        result = subprocess.run(
            ["claude", "mcp", "add", "--scope", "user", "echome", "--", "echome", "mcp", "serve"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            registered.append("Claude Code (user scope)")
        else:
            # Fallback: write to user-level config directly
            _setup_claude_mcp_fallback()
            registered.append("Claude Code (fallback)")
    except FileNotFoundError:
        # claude CLI not available, use fallback
        _setup_claude_mcp_fallback()
        registered.append("Claude Code (fallback)")

    # Codex CLI legacy JSON config. Keep writing it for older clients and humans
    # who inspect the config, but modern Codex reads ~/.codex/config.toml.
    codex_mcp = Path.home() / ".codex" / "mcp.json"
    codex_mcp.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(codex_mcp.read_text()) if codex_mcp.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data.setdefault("mcpServers", {})["echome"] = mcp_config
    codex_mcp.write_text(json.dumps(data, indent=2))
    registered.append(f"Codex CLI legacy ({codex_mcp})")

    codex_toml = Path.home() / ".codex" / "config.toml"
    _upsert_codex_config(codex_toml)
    registered.append(f"Codex CLI ({codex_toml})")

    for r in registered:
        console.print(f"    [green]✓[/green] {r}")


def _upsert_codex_config(path) -> None:
    """Add/update EchoMe in Codex TOML MCP configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        content = path.read_text()
    except OSError:
        content = ""

    block = (
        "\n[mcp_servers.echome]\n"
        "command = \"echome\"\n"
        "args = [\"mcp\", \"serve\"]\n"
        "enabled = true\n"
    )
    pattern = re.compile(r"(?ms)^\[mcp_servers\.echome\]\n.*?(?=^\[|\Z)")

    if pattern.search(content):
        content = pattern.sub(block.lstrip(), content)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += block

    path.write_text(content)


def init(
    hub_url: str = typer.Option("", "--hub-url", "-u", help="Hub URL"),
    token: str = typer.Option("", "--token", "-t", help="Auth token"),
    skip_mcp: bool = typer.Option(False, "--skip-mcp", help="Skip MCP server setup"),
) -> None:
    """Initialize EchoMe: vault + Hub connection + MCP registration."""
    console.print("\n[bold green]━━━ EchoMe Init ━━━[/bold green]\n")

    # ─── Step 1: Hub Connection ───
    console.print("[bold]1. Hub Connection[/bold]")

    if not hub_url:
        hub_url = Prompt.ask("   Hub URL", default="http://localhost:20000")
    if not token:
        token = Prompt.ask("   Auth Token", password=True, default="")

    config = Config(hub_url=hub_url, token=token)

    # Test connection
    if token:
        console.print("   Testing connection...", end=" ")
        try:
            from echome.core.client import HubClient
            client = HubClient(config)
            health = client.health()
            console.print(f"[green]✓ Connected[/green] (Hub v{health.get('version', '?')})")
        except Exception as e:
            console.print(f"[yellow]✗ Failed: {e}[/yellow]")
            console.print("   [dim]You can fix this later in ~/.echome/config.yaml[/dim]")
    else:
        console.print("   [dim]Skipping connection test (no token)[/dim]")

    # Save config + create vault dirs
    config.save()
    ensure_vault_dirs()
    console.print("   [green]✓[/green] Vault created at ~/.echome/\n")

    # ─── Step 2: MCP Server (optional) ───
    console.print("[bold]2. MCP Server[/bold] [dim](让 AI 可以查询你的记忆)[/dim]")

    if skip_mcp:
        console.print("   [dim]Skipped (--skip-mcp)[/dim]\n")
    elif _mcp_available():
        install_mcp = Confirm.ask(
            "   Register MCP server to Claude Code / Codex CLI?",
            default=True,
        )
        if install_mcp:
            _setup_mcp()
            console.print("   [green]✓[/green] MCP registered. Restart AI CLI to activate.\n")
        else:
            console.print("   [dim]Skipped. Run `echome mcp install` later if needed.[/dim]\n")
    else:
        console.print("   [yellow]⚠ MCP 未安装[/yellow]")
        console.print("   [dim]安装 MCP 支持: pip install echome[mcp][/dim]")
        console.print("   [dim]安装后运行 `echome mcp install` 即可注册[/dim]\n")

    # ─── Done ───
    console.print("[bold green]━━━ 初始化完成 ━━━[/bold green]\n")
    console.print("下一步:")
    console.print("  [cyan]eme add[/cyan]      — 添加第一条记忆")
    console.print("  [cyan]eme list[/cyan]     — 查看所有记忆")
    console.print("  [cyan]eme search[/cyan]   — 搜索记忆")
    console.print("  [cyan]eme sync[/cyan]     — 同步到 AI CLI 配置文件")


if __name__ == "__main__":
    typer.run(init)
