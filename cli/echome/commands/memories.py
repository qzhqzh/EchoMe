"""Memory management commands: list, add, edit, search."""

from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from echome.core.client import HubClient
from echome.core.config import Config

console = Console()


def list_memories(
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type"),
    layer: Optional[str] = typer.Option(None, "--layer", "-l", help="Filter by layer (L0/L1/L2)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Filter by tags (comma-separated)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List memories from Hub."""
    config = Config.load()
    client = HubClient(config)

    params: dict = {"limit": limit}
    if type:
        params["type"] = type
    if layer:
        params["layer"] = layer
    if tags:
        params["tags"] = tags

    try:
        result = client.list_memories(**params)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    items = result.get("items", [])
    total = result.get("total", 0)

    if not items:
        console.print("[dim]No memories found.[/dim]")
        return

    table = Table(title=f"Memories ({total} total)")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Layer", style="cyan", width=4)
    table.add_column("Type", style="green", width=12)
    table.add_column("Title", style="bold")
    table.add_column("Priority", justify="center", width=4)
    table.add_column("Tags", style="dim")

    for item in items:
        table.add_row(
            str(item["id"])[:8],
            item["layer"],
            item["type"],
            item["title"],
            str(item["priority"]),
            ", ".join(item.get("tags", [])),
        )

    console.print(table)


def add_memory() -> None:
    """Interactively add a new memory."""
    config = Config.load()
    client = HubClient(config)

    console.print("\n[bold]Add New Memory[/bold]\n")

    title = Prompt.ask("Title")
    content = Prompt.ask("Content (rules/description)")

    type_choices = [
        "persona", "workflow", "tech", "constraint",
        "snippet", "decision", "knowledge", "interaction", "project",
    ]
    mem_type = Prompt.ask(
        "Type",
        choices=type_choices,
        default="workflow",
    )

    layer = Prompt.ask("Layer", choices=["L0", "L1", "L2"], default="L2")
    priority = int(Prompt.ask("Priority (1-10)", default="5"))
    tags_input = Prompt.ask("Tags (comma-separated)", default="")
    tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    is_global = Prompt.ask("Global (all projects)?", choices=["y", "n"], default="y") == "y"

    data = {
        "title": title,
        "content": content,
        "type": mem_type,
        "layer": layer,
        "priority": priority,
        "tags": tags,
        "scope": {
            "global": is_global,
            "projects": [],
            "exclude_projects": [],
        },
        "source": "manual",
    }

    try:
        result = client.create_memory(data)
        console.print(f"\n[green]Memory created![/green] ID: {result['id']}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def search_memories(
    query: str = typer.Argument(..., help="Search query"),
    type: Optional[str] = typer.Option(None, "--type", "-t"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
) -> None:
    """Search memories by keyword/semantic query."""
    config = Config.load()
    client = HubClient(config)

    kwargs: dict = {"top_k": top_k}
    if type:
        kwargs["type"] = type

    try:
        result = client.search(query, **kwargs)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    results = result.get("results", [])
    if not results:
        console.print("[dim]No matching memories found.[/dim]")
        return

    console.print(f"\n[bold]Found {len(results)} results[/bold] (searched {result.get('total_searched', '?')} memories)\n")

    for i, item in enumerate(results, 1):
        score = item.get("score", 0)
        console.print(f"[bold cyan]{i}. {item['title']}[/bold cyan] (score: {score:.2f})")
        console.print(f"   Type: {item['type']} | Tags: {', '.join(item.get('tags', []))}")
        # Show first 200 chars of content
        content = item.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        console.print(f"   {content}\n")
