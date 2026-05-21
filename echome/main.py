"""EchoMe CLI - Main entry point."""

import typer

from echome.commands.init import init
from echome.commands.memories import add_memory, list_memories, search_memories
from echome.commands.review import review
from echome.commands.sync import detect, eject, pull, push, status, sync
from echome.commands.update import update

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
app.command("update")(update)
app.command("review")(review)

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
    try:
        from echome_mcp.server import run_server
        run_server(use_sse=sse)
    except ImportError:
        from rich.console import Console
        console = Console()
        console.print("[red]MCP 未安装。[/red]")
        console.print("安装: [cyan]pip install echome-cli\\[mcp][/cyan]")
        raise typer.Exit(1)


@mcp_app.command("install")
def mcp_install() -> None:
    """Register MCP server in Claude Code and Codex CLI."""
    try:
        import echome_mcp  # noqa: F401
    except ImportError:
        from rich.console import Console
        console = Console()
        console.print("[red]MCP 未安装。[/red]")
        console.print("先安装: [cyan]pip install echome-cli\\[mcp][/cyan]")
        raise typer.Exit(1)

    # Reuse the setup logic from init
    from echome.commands.init import _setup_mcp
    from rich.console import Console
    console = Console()
    console.print("\n[bold]Registering EchoMe MCP Server...[/bold]\n")
    _setup_mcp()
    console.print("\n[green]Done![/green] Restart your AI CLI to activate.\n")


if __name__ == "__main__":
    app()
