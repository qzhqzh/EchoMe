"""echome clean - Remove all EchoMe injected content for a clean environment."""

from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm

from echome.core.client import HubClient
from echome.core.config import Config
from echome.targets.claude import ClaudeCodeTarget
from echome.targets.codex import CodexTarget

console = Console()

ALL_TARGETS = [ClaudeCodeTarget(), CodexTarget()]


def clean(
    scope: str = typer.Option(
        "all",
        "--scope",
        "-s",
        help="What to clean: 'global', 'project', or 'all'",
    ),
    delete_hub_data: bool = typer.Option(
        False,
        "--delete-hub-data",
        help="Also delete all memories from Hub (DESTRUCTIVE!)",
    ),
) -> None:
    """Remove EchoMe injected content for a clean AI environment.

    Scopes:
      global  — Remove from ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md
      project — Remove from current project's CLAUDE.md / AGENTS.md
      all     — Remove both global and project level
    """
    project_dir = Path.cwd()
    console.print("\n[bold yellow]EchoMe Clean[/bold yellow]\n")

    if scope in ("global", "all"):
        console.print("[bold]Global files:[/bold]")
        for t in ALL_TARGETS:
            t.eject_global()
            console.print(f"  [green]✓[/green] Cleaned {t.name}: {t.global_file}")

    if scope in ("project", "all"):
        console.print(f"\n[bold]Project files[/bold] ({project_dir}):")
        for t in ALL_TARGETS:
            pf = t.project_file(project_dir)
            if pf.exists() and "<!-- echome:begin -->" in pf.read_text():
                t.eject_project(project_dir)
                console.print(f"  [green]✓[/green] Cleaned {t.name}: {pf}")
            else:
                console.print(f"  [dim]  {t.name}: nothing to clean[/dim]")

    if delete_hub_data:
        console.print("\n[bold red]⚠ Delete ALL memories from Hub?[/bold red]")
        console.print("[dim]This will permanently remove all your stored memories.[/dim]")
        if Confirm.ask("Are you sure?", default=False):
            config = Config.load()
            client = HubClient(config)
            try:
                # Get all memories and delete them
                result = client.list_memories(limit=200)
                items = result.get("items", [])
                for item in items:
                    client.delete_memory(item["id"], hard=True)
                console.print(f"  [green]✓[/green] Deleted {len(items)} memories from Hub")
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")
        else:
            console.print("  [dim]Skipped.[/dim]")

    console.print("\n[green]Done![/green] Your AI environment is clean.")
    console.print("[dim]Run `echome sync` when you want to re-inject memories.[/dim]")
