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

        dist = importlib.metadata.distribution("echome")
        direct_url = dist.read_text("direct_url.json")
        if direct_url and '"dir_info"' in direct_url:
            return "editable"
        if "github" in (direct_url or ""):
            return "github"
    except Exception:
        pass
    return "github"


def _refresh_mcp_registration() -> None:
    """Best-effort refresh of Claude/Codex MCP registration after update."""
    try:
        import echome_mcp  # noqa: F401
        from echome.commands.init import _setup_mcp
    except ImportError:
        console.print("  [yellow]MCP package not installed; skip MCP registration[/yellow]")
        return

    try:
        console.print("  Refreshing MCP registration...")
        _setup_mcp()
    except Exception as exc:
        console.print(f"  [yellow]MCP registration refresh failed: {exc}[/yellow]")
        console.print("  [dim]Run `echome mcp install` manually if needed.[/dim]")


def _remind_sync() -> None:
    console.print("\n[bold]Don't forget:[/bold]")
    console.print("  [cyan]echome sync[/cyan]  — Re-sync your memories to CLAUDE.md / AGENTS.md")


def _update_editable() -> None:
    console.print("  Install type: [yellow]editable (development)[/yellow]")
    console.print("\n  For editable installs, update manually:")
    console.print("  [cyan]git pull origin main && pip install -e '.[mcp]'[/cyan]")

    try:
        import echome

        echome_path = Path(echome.__file__).parent.parent
        if not (echome_path / ".git").exists():
            return

        console.print(f"\n  Detected repo at: {echome_path}")
        console.print("  Running git pull...")
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=str(echome_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            console.print(f"  [yellow]git pull failed: {result.stderr.strip()}[/yellow]")
            return

        console.print("  [green]✓ Git pull done[/green]")
        pip_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".[mcp]"],
            cwd=str(echome_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if pip_result.returncode != 0:
            console.print("  [red]pip install failed[/red]")
            console.print(f"[dim]{pip_result.stderr[-500:]}[/dim]")
            return

        console.print("  [green]✓ Reinstalled[/green]")
        _refresh_mcp_registration()
        _remind_sync()
    except Exception as exc:
        console.print(f"  [yellow]Editable update skipped: {exc}[/yellow]")


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

    from echome import __version__

    console.print(f"  Current version: [cyan]{__version__}[/cyan]")

    if not source:
        source = _detect_install_source()

    if source == "editable":
        _update_editable()
        return

    if source == "github":
        console.print("  Install source: [cyan]GitHub[/cyan]")
        pip_cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"echome[mcp] @ {GITHUB_REPO}",
        ]
    elif source == "pypi":
        console.print("  Install source: [cyan]PyPI[/cyan]")
        pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "echome[mcp]"]
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
    except subprocess.TimeoutExpired:
        console.print("[red]Update timed out. Check your network.[/red]")
        raise typer.Exit(1) from None

    if result.returncode != 0:
        console.print("[red]Update failed:[/red]")
        console.print(f"[dim]{result.stderr[-500:]}[/dim]")
        raise typer.Exit(1)

    if "already satisfied" in result.stdout.lower():
        console.print("[green]✓ Already up to date![/green]")
    else:
        console.print("[green]✓ Updated successfully![/green]")
        console.print("[dim]Restart your terminal for changes to take effect.[/dim]")

    _refresh_mcp_registration()
    _remind_sync()
