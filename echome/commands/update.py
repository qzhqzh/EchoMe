"""echome update - Self-update EchoMe CLI to the latest version."""

import subprocess
import sys

import typer
from rich.console import Console

console = Console()


def update(
    pre: bool = typer.Option(False, "--pre", help="Include pre-release versions"),
) -> None:
    """Update EchoMe CLI to the latest version."""
    console.print("\n[bold]Checking for updates...[/bold]\n")

    # Determine current version
    from echome import __version__
    console.print(f"  Current version: [cyan]{__version__}[/cyan]")

    # Build pip command
    pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if pre:
        pip_cmd.append("--pre")
    pip_cmd.append("echome-cli[mcp]")

    console.print(f"  Running: [dim]{' '.join(pip_cmd)}[/dim]\n")

    try:
        result = subprocess.run(
            pip_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            # Check if actually updated
            if "already satisfied" in result.stdout.lower() or "already up-to-date" in result.stdout.lower():
                console.print("[green]Already up to date![/green]")
            else:
                console.print("[green]✓ Updated successfully![/green]")
                console.print("[dim]Restart your terminal to use the new version.[/dim]")
        else:
            console.print(f"[red]Update failed:[/red]\n{result.stderr}")
            raise typer.Exit(1)

    except subprocess.TimeoutExpired:
        console.print("[red]Update timed out. Check your network connection.[/red]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("[red]pip not found. Try manually: pip install --upgrade echome-cli[mcp][/red]")
        raise typer.Exit(1)
