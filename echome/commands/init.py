"""echome init - Initialize local vault, configure Hub, and optionally set up MCP."""

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


def _setup_mcp() -> None:
    """Register EchoMe MCP server in Claude Code and Codex CLI."""
    import json
    from pathlib import Path

    mcp_config = {
        "command": "echome",
        "args": ["mcp", "serve"],
    }

    registered = []

    # Claude Code
    claude_mcp = Path.home() / ".claude" / "mcp.json"
    claude_mcp.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(claude_mcp.read_text()) if claude_mcp.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data.setdefault("mcpServers", {})["echome"] = mcp_config
    claude_mcp.write_text(json.dumps(data, indent=2))
    registered.append(f"Claude Code ({claude_mcp})")

    # Codex CLI
    codex_mcp = Path.home() / ".codex" / "mcp.json"
    codex_mcp.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(codex_mcp.read_text()) if codex_mcp.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data.setdefault("mcpServers", {})["echome"] = mcp_config
    codex_mcp.write_text(json.dumps(data, indent=2))
    registered.append(f"Codex CLI ({codex_mcp})")

    for r in registered:
        console.print(f"    [green]✓[/green] {r}")


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
        install_mcp = Confirm.ask("   Register MCP server to Claude Code / Codex CLI?", default=True)
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
