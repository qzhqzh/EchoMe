"""echome seed - Load seed memories for new users."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from echome.core.client import HubClient
from echome.core.config import Config

console = Console()

# Seed file is bundled with the package
SEED_FILE = Path(__file__).parent.parent / "seed_memories.json"


def seed(
    force: bool = typer.Option(False, "--force", "-f", help="Seed even if user has memories"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be seeded without creating"),
) -> None:
    """Load seed memories for your account. Skips duplicates by title."""
    config = Config.load()
    if not config.token:
        console.print("[red]未登录。先运行 `echome login`[/red]")
        raise typer.Exit(1)

    client = HubClient(config)

    # Check Hub connection
    try:
        client.health()
    except Exception as e:
        console.print(f"[red]Hub 连接失败: {e}[/red]")
        raise typer.Exit(1) from None

    # Get existing memory titles
    existing_titles: set[str] = set()
    try:
        result = client.list_memories()
        total = result.get("total", 0)
        if total > 0:
            # Fetch all memories to get titles
            memories = client.list_memories(limit=total).get("items", [])
            existing_titles = {m["title"] for m in memories}
    except Exception as e:
        console.print(f"[red]获取记忆失败: {e}[/red]")
        raise typer.Exit(1) from None

    # Check if user already has memories (skip unless --force)
    total = len(existing_titles)
    if total > 0 and not force:
        console.print(f"[yellow]已有 {total} 条记忆，跳过 seed[/yellow]")
        console.print("使用 [cyan]--force[/cyan] 强制执行（仍会跳过重复 title）")
        raise typer.Exit(0)

    # Load seed data
    if not SEED_FILE.exists():
        console.print(f"[red]Seed 文件不存在: {SEED_FILE}[/red]")
        raise typer.Exit(1)

    seed_data = json.loads(SEED_FILE.read_text())

    # Filter out duplicates
    to_seed = []
    skipped = []
    for item in seed_data:
        if item["title"] in existing_titles:
            skipped.append(item["title"])
        else:
            to_seed.append(item)

    if not to_seed:
        console.print("[green]所有 seed 记忆已存在，无需创建[/green]")
        if skipped:
            console.print(f"[dim]已跳过: {', '.join(skipped)}[/dim]")
        raise typer.Exit(0)

    # Dry run mode
    if dry_run:
        console.print(f"\n[bold]将创建 {len(to_seed)} 条 seed 记忆:[/bold]\n")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Title")
        table.add_column("Type")
        table.add_column("Layer")
        for item in to_seed:
            table.add_row(item["title"], item["type"], item["layer"])
        console.print(table)
        if skipped:
            console.print(f"\n[dim]已跳过重复: {len(skipped)} 条[/dim]")
        raise typer.Exit(0)

    # Create memories
    console.print(f"\n[bold]正在创建 {len(to_seed)} 条 seed 记忆...[/bold]\n")
    created = 0
    failed = 0

    for item in to_seed:
        try:
            memory_data = {
                "title": item["title"],
                "content": item["content"],
                "type": item["type"],
                "layer": item["layer"],
                "priority": item["priority"],
                "tags": item["tags"],
                "status": item["status"],
                "scope": {
                    "global": item["scope"]["global"],
                    "projects": item["scope"].get("projects", []),
                    "exclude_projects": item["scope"].get("exclude_projects", []),
                },
                "source": item["source"],
                "visibility": item.get("visibility", "private"),
            }
            client.create_memory(memory_data)
            console.print(f"  [green]✓[/green] {item['title']}")
            created += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] {item['title']}: {e}")
            failed += 1

    console.print()
    console.print(f"[green]创建成功: {created}[/green]")
    if failed:
        console.print(f"[red]创建失败: {failed}[/red]")
    if skipped:
        console.print(f"[dim]跳过重复: {len(skipped)}[/dim]")
