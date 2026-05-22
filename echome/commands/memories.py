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
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
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
    if status:
        params["status"] = status

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


def add_memory(
    title: Optional[str] = typer.Argument(None, help="Memory title (quick mode)"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="Memory content"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Memory type"),
    layer: Optional[str] = typer.Option(None, "--layer", "-l", help="Layer (L0/L1/L2)"),
    priority: Optional[int] = typer.Option(None, "--priority", "-p", help="Priority (1-10)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Tags (comma-separated)"),
) -> None:
    """Add a new memory. Supports quick mode (with args) or interactive mode."""
    config = Config.load()
    client = HubClient(config)

    # Quick mode: if title provided as argument
    if title and content:
        # Fully specified via flags
        data = _build_memory_data(
            title=title,
            content=content,
            mem_type=type or "workflow",
            layer=layer or "L2",
            priority=priority or 5,
            tags=tags or "",
            is_global=True,
        )
    elif title:
        # Title given, prompt for the rest
        console.print(f"\n[bold]Adding memory:[/bold] {title}\n")
        if not content:
            content = Prompt.ask("Content (description/rules)")

        type_choices = [
            "identity", "guardrail", "reasoning", "method", "stack",
            "style", "decision", "context", "template", "project",
        ]
        if not type:
            type = Prompt.ask("Type", choices=type_choices, default="context")
        if not layer:
            layer = Prompt.ask("Layer", choices=["L0", "L1", "L2"], default="L2")
        if priority is None:
            priority = int(Prompt.ask("Priority (1-10)", default="5"))
        if tags is None:
            tags = Prompt.ask("Tags (comma-separated)", default="")

        is_global = Prompt.ask("Global?", choices=["y", "n"], default="y") == "y"

        data = _build_memory_data(
            title=title,
            content=content,
            mem_type=type,
            layer=layer,
            priority=priority,
            tags=tags,
            is_global=is_global,
        )
    else:
        # Fully interactive mode
        console.print("\n[bold]Add New Memory[/bold]\n")

        title = Prompt.ask("Title")
        content = Prompt.ask("Content (description/rules)")

        type_choices = [
            "identity", "guardrail", "reasoning", "method", "stack",
            "style", "decision", "context", "template", "project",
        ]
        mem_type = Prompt.ask("Type", choices=type_choices, default="context")
        layer_val = Prompt.ask("Layer", choices=["L0", "L1", "L2"], default="L2")
        priority_val = int(Prompt.ask("Priority (1-10)", default="5"))
        tags_input = Prompt.ask("Tags (comma-separated)", default="")
        is_global = Prompt.ask("Global?", choices=["y", "n"], default="y") == "y"

        data = _build_memory_data(
            title=title,
            content=content,
            mem_type=mem_type,
            layer=layer_val,
            priority=priority_val,
            tags=tags_input,
            is_global=is_global,
        )

    try:
        result = client.create_memory(data)
        console.print(f"\n[green]✓ Memory created![/green] ID: {result['id']}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


VALID_TYPES = {
    "identity", "guardrail", "reasoning", "method", "stack",
    "style", "decision", "context", "template", "project",
}

TYPE_ALIASES = {
    "feedback": "style", "preference": "style", "interaction": "style",
    "rule": "method", "rules": "method", "process": "method", "convention": "method",
    "workflow": "method",
    "technology": "stack", "technical": "stack", "tech": "stack", "tool": "stack",
    "framework": "stack", "tools": "stack",
    "limit": "guardrail", "boundary": "guardrail", "forbidden": "guardrail",
    "constraint": "guardrail", "red_line": "guardrail",
    "code": "template", "snippet": "template",
    "background": "project",
    "info": "context", "fact": "context", "domain": "context", "knowledge": "context",
    "architecture": "decision", "choice": "decision",
    "persona": "identity", "character": "identity",
    "thinking": "reasoning", "framework": "reasoning",
}


def _normalize_type(raw_type: str) -> str:
    """Normalize memory type, mapping aliases to valid types."""
    t = raw_type.lower().strip()
    if t in VALID_TYPES:
        return t
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    return "context"


def _build_memory_data(
    title: str,
    content: str,
    mem_type: str,
    layer: str,
    priority: int,
    tags: str,
    is_global: bool,
) -> dict:
    """Build the memory data dict for API submission."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    normalized_type = _normalize_type(mem_type)
    return {
        "title": title,
        "content": content,
        "type": normalized_type,
        "layer": layer,
        "priority": priority,
        "tags": tag_list,
        "scope": {
            "global": is_global,
            "projects": [],
            "exclude_projects": [],
        },
        "source": "manual",
    }


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
        content = item.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        console.print(f"   {content}\n")
