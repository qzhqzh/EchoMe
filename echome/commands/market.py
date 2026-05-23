"""Market commands: browse, search, fork public memories."""

import typer
from rich.console import Console
from rich.table import Table

from echome.core.client import HubClient
from echome.core.config import Config

console = Console()

market_app = typer.Typer(help="Browse and fork public memories from the market")


def _market_client() -> HubClient:
    """Create a HubClient (auth optional for read-only)."""
    return HubClient(Config.load())


@market_app.callback(invoke_without_command=True)
def market_default(ctx: typer.Context) -> None:
    """Show market stats when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return

    client = _market_client()
    with client._client() as http_client:
        resp = http_client.get("/api/v1/market/stats")
        resp.raise_for_status()
        stats = resp.json()

    console.print("\n[bold cyan]📚 EchoMe Memory Market[/bold cyan]\n")
    console.print(f"  Total public memories: [green]{stats['total_public']}[/green]")
    console.print(f"  New in last 7 days:    [green]{stats['recent_count_7d']}[/green]")

    if stats.get("by_type"):
        console.print("\n  [bold]By type:[/bold]")
        for t, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
            console.print(f"    {t:<16} {count}")

    console.print(
        "\n[dim]Commands: echome market search <query> | "
        "echome market browse | echome market fork <id>[/dim]\n"
    )


@market_app.command("browse")
def browse(
    type: str = typer.Option(None, "--type", "-t", help="Filter by memory type"),  # noqa: A002
    layer: str = typer.Option(None, "--layer", "-l", help="Filter by layer (L0/L1/L2)"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags to filter"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """Browse public memories in the market."""
    client = _market_client()
    params: dict = {"limit": limit, "offset": offset}
    if type:
        params["type"] = type
    if layer:
        params["layer"] = layer
    if tags:
        params["tags"] = tags

    with client._client() as http_client:
        resp = http_client.get("/api/v1/market/memories", params=params)
        resp.raise_for_status()
        data = resp.json()

    if not data["items"]:
        console.print("[dim]No public memories found.[/dim]\n")
        return

    table = Table(title=f"Market ({data['total']} total)")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Title", style="bold")
    table.add_column("Type", style="cyan")
    table.add_column("Layer")
    table.add_column("Tags", style="green")
    table.add_column("Tokens", justify="right")

    for item in data["items"]:
        short_id = str(item["id"])[:8]
        tags_str = ", ".join(item.get("tags", [])[:3])
        table.add_row(
            short_id,
            item["title"][:50],
            item["type"],
            item["layer"],
            tags_str,
            str(item.get("token_count", 0)),
        )

    console.print(table)
    console.print(
        f"\n[dim]Showing {data['offset'] + 1}-"
        f"{data['offset'] + len(data['items'])} of {data['total']}[/dim]\n"
    )


@market_app.command("search")
def search(
    query: str = typer.Argument(..., help="Search keywords"),
    type: str = typer.Option(None, "--type", "-t", help="Filter by memory type"),  # noqa: A002
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results"),
) -> None:
    """Search public memories by keyword."""
    client = _market_client()
    params: dict = {"q": query, "limit": limit}
    if type:
        params["type"] = type

    with client._client() as http_client:
        resp = http_client.get("/api/v1/market/memories", params=params)
        resp.raise_for_status()
        data = resp.json()

    if not data["items"]:
        console.print(f"[dim]No results for '{query}'[/dim]\n")
        return

    table = Table(title=f"Search: '{query}' ({data['total']} results)")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Title", style="bold")
    table.add_column("Type", style="cyan")
    table.add_column("Layer")
    table.add_column("Tags", style="green")

    for item in data["items"]:
        short_id = str(item["id"])[:8]
        tags_str = ", ".join(item.get("tags", [])[:3])
        table.add_row(short_id, item["title"][:50], item["type"], item["layer"], tags_str)

    console.print(table)
    console.print()


@market_app.command("fork")
def fork(
    memory_id: str = typer.Argument(..., help="UUID of the public memory to fork"),
) -> None:
    """Fork a public memory into your personal library."""
    config = Config.load()
    if not config.token:
        console.print("[red]Not logged in.[/red] Run [cyan]echome login[/cyan] first.\n")
        raise typer.Exit(1)

    client = HubClient(config)
    with client._client() as http_client:
        resp = http_client.post(f"/api/v1/market/memories/{memory_id}/fork")
        if resp.status_code == 404:
            console.print("[red]Memory not found or not public.[/red]\n")
            raise typer.Exit(1)
        if resp.status_code == 400:
            console.print(f"[yellow]{resp.json().get('detail', 'Bad request')}[/yellow]\n")
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

    console.print(f"[green]✓ Forked![/green] New memory: {data['id']}")
    console.print(f"  Title: {data['title']}")
    console.print(f"  Source: {data['forked_from']}\n")


@market_app.command("publish")
def publish(
    memory_id: str = typer.Argument(..., help="UUID of your memory to make public"),
) -> None:
    """Set one of your memories as public (visible in market)."""
    config = Config.load()
    if not config.token:
        console.print("[red]Not logged in.[/red] Run [cyan]echome login[/cyan] first.\n")
        raise typer.Exit(1)

    client = HubClient(config)
    with client._client() as http_client:
        resp = http_client.patch(
            f"/api/v1/memories/{memory_id}",
            json={"visibility": "public"},
        )
        if resp.status_code == 404:
            console.print("[red]Memory not found.[/red]\n")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]✓ Memory {memory_id[:8]}... is now public.[/green]\n")


@market_app.command("unpublish")
def unpublish(
    memory_id: str = typer.Argument(..., help="UUID of your memory to make private"),
) -> None:
    """Set one of your memories as private (hide from market)."""
    config = Config.load()
    if not config.token:
        console.print("[red]Not logged in.[/red] Run [cyan]echome login[/cyan] first.\n")
        raise typer.Exit(1)

    client = HubClient(config)
    with client._client() as http_client:
        resp = http_client.patch(
            f"/api/v1/memories/{memory_id}",
            json={"visibility": "private"},
        )
        if resp.status_code == 404:
            console.print("[red]Memory not found.[/red]\n")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]✓ Memory {memory_id[:8]}... is now private.[/green]\n")
