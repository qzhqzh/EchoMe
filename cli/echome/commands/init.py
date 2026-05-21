"""echome init - Initialize local vault and configure Hub connection."""

import typer
from rich.console import Console
from rich.prompt import Prompt

from echome.core.config import Config, ensure_vault_dirs

console = Console()


def init() -> None:
    """Initialize EchoMe: create ~/.echome/ and configure Hub connection."""
    console.print("\n[bold green]EchoMe Init[/bold green]")
    console.print("Setting up your personal memory vault...\n")

    # Get Hub URL
    hub_url = Prompt.ask(
        "Hub URL",
        default="http://localhost:8000",
    )

    # Get token
    token = Prompt.ask("Auth Token", password=True)

    if not token:
        console.print("[yellow]Warning: No token provided. You can set it later in config.[/yellow]")

    # Create config
    config = Config(hub_url=hub_url, token=token)

    # Test connection
    console.print("\nTesting connection...", end=" ")
    try:
        from echome.core.client import HubClient

        client = HubClient(config)
        health = client.health()
        console.print(f"[green]Connected![/green] (Hub v{health.get('version', '?')})")
    except Exception as e:
        console.print(f"[yellow]Connection failed: {e}[/yellow]")
        console.print("[dim]You can fix the connection later by editing ~/.echome/config.yaml[/dim]")

    # Save config and create directories
    config.save()
    ensure_vault_dirs()

    console.print("\n[green]Done![/green] Your vault is ready at ~/.echome/")
    console.print("\nNext steps:")
    console.print("  echome add        — Add your first memory")
    console.print("  echome sync       — Sync memories to your AI CLI")
    console.print("  echome mcp serve  — Start MCP server for AI access")


if __name__ == "__main__":
    typer.run(init)
