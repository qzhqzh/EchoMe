"""EchoMe CLI - Main entry point."""

import typer

from echome.commands.init import init
from echome.commands.memories import add_memory, list_memories, search_memories
from echome.commands.sync import detect, eject, pull, push, status, sync

app = typer.Typer(
    name="echome",
    help="EchoMe - Personal memory sync for AI CLI tools",
    no_args_is_help=True,
)

# Core commands
app.command("init")(init)
app.command("list")(list_memories)
app.command("add")(add_memory)
app.command("search")(search_memories)

# Sync commands
app.command("sync")(sync)
app.command("push")(push)
app.command("pull")(pull)
app.command("detect")(detect)
app.command("status")(status)
app.command("eject")(eject)


# MCP subcommand group
mcp_app = typer.Typer(help="MCP Server management")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    sse: bool = typer.Option(False, "--sse", help="Use SSE transport instead of stdio"),
) -> None:
    """Start the EchoMe MCP server."""
    from echome_mcp.server import run_server

    run_server(use_sse=sse)


@mcp_app.command("install")
def mcp_install() -> None:
    """Auto-configure MCP in Claude Code and Codex CLI."""
    import json
    from pathlib import Path

    from rich.console import Console

    console = Console()
    console.print("\n[bold]Installing EchoMe MCP Server...[/bold]\n")

    mcp_config = {
        "command": "echome",
        "args": ["mcp", "serve"],
    }

    # Claude Code
    claude_mcp = Path.home() / ".claude" / "mcp.json"
    claude_mcp.parent.mkdir(parents=True, exist_ok=True)

    if claude_mcp.exists():
        data = json.loads(claude_mcp.read_text())
    else:
        data = {"mcpServers": {}}

    data.setdefault("mcpServers", {})["echome"] = mcp_config
    claude_mcp.write_text(json.dumps(data, indent=2))
    console.print(f"  [green]✓[/green] Claude Code: {claude_mcp}")

    # Codex CLI
    codex_mcp = Path.home() / ".codex" / "mcp.json"
    codex_mcp.parent.mkdir(parents=True, exist_ok=True)

    if codex_mcp.exists():
        data = json.loads(codex_mcp.read_text())
    else:
        data = {"mcpServers": {}}

    data.setdefault("mcpServers", {})["echome"] = mcp_config
    codex_mcp.write_text(json.dumps(data, indent=2))
    console.print(f"  [green]✓[/green] Codex CLI: {codex_mcp}")

    console.print("\n[green]MCP installed![/green] Restart your AI CLI to activate.")


if __name__ == "__main__":
    app()
