"""Sync commands: sync, push, pull, detect, status, eject."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from echome.core.client import HubClient
from echome.core.config import Config
from echome.targets.claude import ClaudeCodeTarget
from echome.targets.codex import CodexTarget

console = Console()

ALL_TARGETS = [ClaudeCodeTarget(), CodexTarget()]


def detect() -> None:
    """Detect which AI CLI targets are active in the current directory."""
    project_dir = Path.cwd()
    console.print(f"\n[bold]Detecting AI CLIs in:[/bold] {project_dir}\n")

    found = False
    for target in ALL_TARGETS:
        if target.detect(project_dir):
            console.print(f"  [green]✓[/green] {target.name}")
            found = True
        else:
            console.print(f"  [dim]✗ {target.name}[/dim]")

    if not found:
        console.print("\n[yellow]No AI CLI detected. Sync will use global files only.[/yellow]")


def sync(
    target: Optional[str] = typer.Option(None, "--target", "-t", help="Target: claude, codex"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be changed"),
) -> None:
    """Render and inject memories into AI CLI configuration files."""
    config = Config.load()
    client = HubClient(config)
    project_dir = Path.cwd()

    # Determine targets
    if target:
        target_map = {"claude": ClaudeCodeTarget(), "codex": CodexTarget()}
        targets = [target_map[target]] if target in target_map else []
        if not targets:
            console.print(f"[red]Unknown target: {target}. Use 'claude' or 'codex'.[/red]")
            raise typer.Exit(1)
    else:
        targets = [t for t in ALL_TARGETS if t.detect(project_dir)]
        if not targets:
            # Default to all targets for global injection
            targets = ALL_TARGETS

    for t in targets:
        console.print(f"\n[bold]Syncing to {t.name}...[/bold]")

        # Render L0 (global)
        try:
            result = client.render(target="claude" if isinstance(t, ClaudeCodeTarget) else "codex")
        except Exception as e:
            console.print(f"  [red]Error fetching from Hub: {e}[/red]")
            continue

        content = result.get("content", "")
        included = result.get("memories_included", 0)
        truncated = result.get("memories_truncated", 0)
        token_count = result.get("token_count", 0)

        if dry_run:
            console.print(f"  [dim]Would inject {included} memories ({token_count} tokens) into {t.global_file}[/dim]")
            if truncated:
                console.print(f"  [yellow]  {truncated} memories would be truncated (token limit)[/yellow]")
            console.print(f"\n  [dim]--- Preview ---[/dim]")
            console.print(content[:500])
            if len(content) > 500:
                console.print("  [dim]...(truncated preview)[/dim]")
        else:
            t.inject_global(content)
            console.print(f"  [green]✓[/green] Global: {t.global_file} ({included} memories, {token_count} tokens)")
            if truncated:
                console.print(f"  [yellow]  ⚠ {truncated} memories truncated (token limit exceeded)[/yellow]")

    if not dry_run:
        console.print("\n[green]Sync complete![/green]")


def push() -> None:
    """Push local vault changes to Hub."""
    config = Config.load()
    client = HubClient(config)

    console.print("\n[bold]Pushing to Hub...[/bold]")

    # TODO: Read local vault files and push to Hub
    # For now, placeholder
    try:
        result = client.push([], client_info=f"echome-cli/0.1.0")
        console.print(
            f"  Created: {result.get('created', 0)} | "
            f"Updated: {result.get('updated', 0)} | "
            f"Unchanged: {result.get('unchanged', 0)}"
        )
        console.print("[green]Push complete![/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def pull() -> None:
    """Pull latest memories from Hub to local vault."""
    config = Config.load()
    client = HubClient(config)

    console.print("\n[bold]Pulling from Hub...[/bold]")

    try:
        result = client.pull()
        total = result.get("total", 0)
        console.print(f"  Received {total} memories")
        # TODO: Write to local vault files
        console.print("[green]Pull complete![/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def status() -> None:
    """Show current EchoMe injection status."""
    project_dir = Path.cwd()
    console.print(f"\n[bold]EchoMe Status[/bold] — {project_dir}\n")

    marker = "<!-- echome:begin -->"

    for t in ALL_TARGETS:
        gf = t.global_file
        if gf.exists() and marker in gf.read_text():
            console.print(f"  [green]✓[/green] {t.name} global: {gf}")
        else:
            console.print(f"  [dim]✗ {t.name} global: not injected[/dim]")

        pf = t.project_file(project_dir)
        if pf.exists():
            console.print(f"  [green]✓[/green] {t.name} project: {pf}")
        else:
            console.print(f"  [dim]✗ {t.name} project: not injected[/dim]")


def eject() -> None:
    """Remove all EchoMe injected content."""
    project_dir = Path.cwd()
    console.print("\n[bold yellow]Ejecting EchoMe content...[/bold yellow]\n")

    for t in ALL_TARGETS:
        t.eject_global()
        console.print(f"  [green]✓[/green] Cleaned {t.name} global file")
        t.eject_project(project_dir)
        console.print(f"  [green]✓[/green] Cleaned {t.name} project file")

    console.print("\n[green]Eject complete. All EchoMe content removed.[/green]")
