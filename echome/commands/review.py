"""echome review - Review and approve/reject AI-suggested memories."""

from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt

from echome.core.client import HubClient
from echome.core.config import Config

console = Console()


def review(
    approve_all: bool = typer.Option(False, "--approve-all", help="Approve all pending"),
    reject_all: bool = typer.Option(False, "--reject-all", help="Reject all pending"),
) -> None:
    """Review AI-suggested memories (status: pending)."""
    config = Config.load()
    client = HubClient(config)

    try:
        result = client.list_memories(status="pending")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    items = result.get("items", [])
    if not items:
        console.print("[green]No pending memories to review.[/green]")
        return

    console.print(f"\n[bold]Pending memories: {len(items)}[/bold]\n")

    if approve_all:
        for item in items:
            client.update_memory(item["id"], {"status": "active"})
        console.print(f"[green]✓ Approved {len(items)} memories.[/green]")
        return

    if reject_all:
        for item in items:
            client.delete_memory(item["id"])
        console.print(f"[yellow]✗ Rejected {len(items)} memories.[/yellow]")
        return

    # Interactive review
    for i, item in enumerate(items, 1):
        console.print(f"\n[bold cyan]── {i}/{len(items)} ──[/bold cyan]")
        console.print(f"[bold]{item['title']}[/bold]")
        console.print(f"Type: {item['type']} | Tags: {', '.join(item.get('tags', []))}")

        try:
            full = client.get_memory(item["id"])
            console.print(f"\n{full.get('content', '')}\n")
        except Exception:
            pass

        action = Prompt.ask("[a]pprove / [r]eject / [s]kip / [q]uit", default="s")

        if action == "a":
            client.update_memory(item["id"], {"status": "active"})
            console.print("  [green]✓ Approved[/green]")
        elif action == "r":
            client.delete_memory(item["id"])
            console.print("  [yellow]✗ Rejected[/yellow]")
        elif action == "q":
            break
