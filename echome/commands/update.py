"""echome update - Self-update EchoMe CLI to the latest version."""

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

console = Console()

# GitHub repo URL for installation
GITHUB_REPO = "git+https://github.com/qzhqzh/EchoMe.git"


def _detect_install_source() -> str:
    """Detect how echome was installed: 'editable', 'github', or 'pypi'."""
    try:
        import importlib.metadata
        dist = importlib.metadata.distribution("echome-cli")
        # Check if it's an editable install (has direct_url.json pointing to local path)
        direct_url = dist.read_text("direct_url.json")
        if direct_url and '"dir_info"' in direct_url:
            return "editable"
        if "github" in (direct_url or ""):
            return "github"
    except Exception:
        pass
    return "github"  # Default to github


def update(
    source: str = typer.Option(
        "",
        "--source",
        "-s",
        help="Install source: 'github' (default) or 'pypi'",
    ),
) -> None:
    """Update EchoMe CLI to the latest version from GitHub."""
    console.print("\n[bold]EchoMe Update[/bold]\n")

    # Show current version
    from echome import __version__
    console.print(f"  Current version: [cyan]{__version__}[/cyan]")

    # Determine install method
    if not source:
        source = _detect_install_source()

    if source == "editable":
        # Editable install — user should git pull manually
        console.print("  Install type: [yellow]editable (development)[/yellow]")
        console.print("\n  For editable installs, update manually:")
        console.print("  [cyan]git pull origin main && pip install -e '.[mcp]'[/cyan]")

        # Offer to do it automatically if we can find the repo
        try:
            import echome
            echome_path = Path(echome.__file__).parent.parent
            if (echome_path / ".git").exists():
                console.print(f"\n  Detected repo at: {echome_path}")
                console.print("  Running git pull...")
                result = subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=str(echome_path),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    console.print(f"  [green]✓ Git pull done[/green]")
                    # Reinstall
                    pip_result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "-e", ".[mcp]"],
                        cwd=str(echome_path),
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if pip_result.returncode == 0:
                        console.print("  [green]✓ Reinstalled[/green]")
                    else:
                        console.print(f"  [red]pip install failed[/red]")
                else:
                    console.print(f"  [yellow]git pull failed: {result.stderr.strip()}[/yellow]")
        except Exception:
            pass
        return

    elif source == "github":
        # Install from GitHub
        console.print("  Install source: [cyan]GitHub[/cyan]")
        pip_cmd = [
            sys.executable, "-m", "pip", "install", "--upgrade",
            f"echome-cli[mcp] @ {GITHUB_REPO}",
        ]

    elif source == "pypi":
        # Install from PyPI
        console.print("  Install source: [cyan]PyPI[/cyan]")
        pip_cmd = [
            sys.executable, "-m", "pip", "install", "--upgrade",
            "echome-cli[mcp]",
        ]
    else:
        console.print(f"[red]Unknown source: {source}. Use 'github' or 'pypi'.[/red]")
        raise typer.Exit(1)

    console.print(f"  Running: [dim]{' '.join(pip_cmd)}[/dim]\n")

    try:
        result = subprocess.run(
            pip_cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode == 0:
            if "already satisfied" in result.stdout.lower():
                console.print("[green]✓ Already up to date![/green]")
            else:
                console.print("[green]✓ Updated successfully![/green]")
                console.print("[dim]Restart your terminal for changes to take effect.[/dim]")

                # Remind to re-sync
                console.print("\n[bold]Don't forget:[/bold]")
                console.print("  [cyan]eme sync[/cyan]  — Re-sync your memories to CLAUDE.md")
        else:
            console.print(f"[red]Update failed:[/red]")
            console.print(f"[dim]{result.stderr[-500:]}[/dim]")
            raise typer.Exit(1)

    except subprocess.TimeoutExpired:
        console.print("[red]Update timed out. Check your network.[/red]")
        raise typer.Exit(1)
