"""EchoMe CLI - Main entry point."""

import json
import os
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from echome.commands.init import init
from echome.commands.login import login, logout, whoami
from echome.commands.market import market_app
from echome.commands.memories import add_memory, list_memories, search_memories
from echome.commands.review import review
from echome.commands.clean import clean
from echome.commands.sync import detect, eject, pull, push, sync
from echome.commands.update import update

console = Console()


def _get_hub_status(config):
    """Check Hub connectivity and get memory stats."""
    if not config.token:
        return "[dim]not configured[/dim]", "[dim]run `echome init` first[/dim]"
    try:
        from echome.core.client import HubClient
        client = HubClient(config)
        client.health()

        result = client.list_memories(limit=1)
        total = result.get("total", 0)
        l0 = client.list_memories(layer="L0", limit=1).get("total", 0)
        l1 = client.list_memories(layer="L1", limit=1).get("total", 0)
        l2 = total - l0 - l1

        hub = f"[green]✓ Connected[/green] ({config.hub_url})"
        mem = f"[green]{total}[/green] active ({l0} L0, {l1} L1, {l2} L2)"
        return hub, mem
    except Exception:
        return f"[yellow]✗ Unreachable[/yellow] ({config.hub_url})", "[dim]unavailable[/dim]"


def _get_mcp_status():
    """Check if MCP is registered in Claude Code."""
    claude_mcp = Path.home() / ".claude" / "mcp.json"
    if claude_mcp.exists():
        try:
            data = json.loads(claude_mcp.read_text())
            if "echome" in data.get("mcpServers", {}):
                return "[green]✓ Registered[/green] (Claude Code)"
        except Exception:
            pass
    return "[dim]not registered[/dim]"


def _get_last_sync():
    """Get last sync time from CLAUDE.md modification time."""
    claude_global = Path.home() / ".claude" / "CLAUDE.md"
    if claude_global.exists():
        try:
            content = claude_global.read_text()
            if "<!-- echome:begin -->" in content:
                mtime = os.path.getmtime(claude_global)
                sync_time = datetime.fromtimestamp(mtime)
                diff = datetime.now() - sync_time
                if diff.days > 0:
                    return f"[yellow]{diff.days}d ago[/yellow]"
                elif diff.seconds > 3600:
                    return f"[green]{diff.seconds // 3600}h ago[/green]"
                else:
                    return f"[green]{diff.seconds // 60}m ago[/green]"
        except Exception:
            pass
    return "[dim]never[/dim]"


def _welcome_callback(ctx: typer.Context) -> None:
    """Show welcome banner when no command is given."""
    if ctx.invoked_subcommand is not None:
        return

    from echome import __version__
    from echome.core.config import Config

    config = Config.load()
    hub_status, memory_stats = _get_hub_status(config)
    mcp_status = _get_mcp_status()
    last_sync = _get_last_sync()

    console.print()
    console.print(Panel.fit(
        "\n".join([
            f"[bold cyan]⚡ EchoMe[/bold cyan] [dim]v{__version__}[/dim]",
            "[italic]   Switch AI, not yourself.[/italic]",
            "",
            f"  Hub:       {hub_status}",
            f"  Memories:  {memory_stats}",
            f"  MCP:       {mcp_status}",
            f"  Last sync: {last_sync}",
        ]),
        border_style="cyan",
    ))

    console.print("\n[bold]Commands:[/bold]")
    console.print("  [cyan]echome add[/cyan]       Add a memory")
    console.print("  [cyan]echome list[/cyan]      List memories")
    console.print("  [cyan]echome sync[/cyan]      Sync to CLAUDE.md")
    console.print("  [cyan]echome search[/cyan]    Search memories")
    console.print("  [cyan]echome status[/cyan]    Detailed status")
    console.print("  [cyan]echome update[/cyan]    Update EchoMe")
    console.print("  [cyan]echome --help[/cyan]    All commands")
    console.print()


def status_cmd() -> None:
    """Show detailed EchoMe status: Hub, MCP, sync, memories."""
    from echome import __version__
    from echome.core.config import Config
    from echome.targets.claude import ClaudeCodeTarget
    from echome.targets.codex import CodexTarget

    config = Config.load()
    project_dir = Path.cwd()

    console.print(f"\n[bold]EchoMe Status[/bold] v{__version__}")
    console.print(f"[dim]Project: {project_dir}[/dim]\n")

    # Hub
    hub_status, memory_stats = _get_hub_status(config)
    console.print(f"  [bold]Hub:[/bold]       {hub_status}")
    console.print(f"  [bold]Memories:[/bold]  {memory_stats}")

    # MCP
    mcp_status = _get_mcp_status()
    console.print(f"  [bold]MCP:[/bold]       {mcp_status}")

    # MCP process check — cross-platform
    try:
        import platform
        import subprocess

        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            if "echome" in result.stdout.lower():
                console.print(f"  [bold]MCP Proc:[/bold]  [green]✓ Running[/green]")
            else:
                console.print(f"  [bold]MCP Proc:[/bold]  [dim]not running (starts on-demand by AI CLI)[/dim]")
        else:
            result = subprocess.run(
                ["pgrep", "-f", "echome mcp serve"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                console.print(f"  [bold]MCP Proc:[/bold]  [green]✓ Running[/green] (PID {result.stdout.strip().split()[0]})")
            else:
                console.print(f"  [bold]MCP Proc:[/bold]  [dim]not running (starts on-demand by AI CLI)[/dim]")
    except Exception:
        console.print(f"  [bold]MCP Proc:[/bold]  [dim]unknown[/dim]")

    # Sync status
    last_sync = _get_last_sync()
    console.print(f"  [bold]Last sync:[/bold] {last_sync}")

    # File injection status
    marker = "<!-- echome:begin -->"
    targets = [ClaudeCodeTarget(), CodexTarget()]

    console.print(f"\n[bold]Injection Status:[/bold]")
    for t in targets:
        gf = t.global_file
        if gf.exists() and marker in gf.read_text():
            console.print(f"  [green]✓[/green] {t.name} global: {gf}")
        else:
            console.print(f"  [dim]✗[/dim] {t.name} global: not injected")

        pf = t.project_file(project_dir)
        if pf.exists() and marker in pf.read_text():
            console.print(f"  [green]✓[/green] {t.name} project: {pf}")
        else:
            console.print(f"  [dim]✗[/dim] {t.name} project: not injected")

    # Config
    console.print(f"\n[bold]Config:[/bold]")
    console.print(f"  Vault:  ~/.echome/")
    console.print(f"  Config: ~/.echome/config.yaml")
    console.print(f"  Hub:    {config.hub_url}")
    console.print()


app = typer.Typer(
    name="echome",
    help="EchoMe - Personal memory sync for AI CLI tools",
    invoke_without_command=True,
    callback=_welcome_callback,
)

# Core commands
app.command("init")(init)
app.command("list")(list_memories)
app.command("add")(add_memory)
app.command("search")(search_memories)
app.command("update")(update)
app.command("review")(review)
app.command("clean")(clean)
app.command("status")(status_cmd)

# Auth commands
app.command("login")(login)
app.command("logout")(logout)
app.command("whoami")(whoami)

# Sync commands
app.command("sync")(sync)
app.command("push")(push)
app.command("pull")(pull)
app.command("detect")(detect)
app.command("eject")(eject)

# Market subcommand group
app.add_typer(market_app, name="market")


# MCP subcommand group
mcp_app = typer.Typer(help="MCP Server management")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    sse: bool = typer.Option(False, "--sse", help="Use SSE transport instead of stdio"),
) -> None:
    """Start the EchoMe MCP server."""
    try:
        from echome_mcp.server import run_server
        run_server(use_sse=sse)
    except ImportError:
        console.print("[red]MCP 未安装。[/red]")
        console.print("安装: [cyan]pip install echome-cli\\[mcp][/cyan]")
        raise typer.Exit(1)


@mcp_app.command("install")
def mcp_install() -> None:
    """Register MCP server in Claude Code and Codex CLI."""
    try:
        import echome_mcp  # noqa: F401
    except ImportError:
        console.print("[red]MCP 未安装。[/red]")
        console.print("先安装: [cyan]pip install echome-cli\\[mcp][/cyan]")
        raise typer.Exit(1)

    from echome.commands.init import _setup_mcp
    console.print("\n[bold]Registering EchoMe MCP Server...[/bold]\n")
    _setup_mcp()
    console.print("\n[green]Done![/green] Restart your AI CLI to activate.\n")


if __name__ == "__main__":
    app()
