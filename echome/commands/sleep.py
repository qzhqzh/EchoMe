"""Memory Sleep CLI commands."""

import json
from pathlib import Path

import typer
from rich.console import Console

from echome.core.client import HubClient
from echome.core.config import Config

console = Console()
sleep_app = typer.Typer(help="Memory Sleep planning and apply")


@sleep_app.command("candidates")
def candidates(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    session_id: str | None = typer.Option(None, "--session-id", help="Existing sleep session ID"),
    scope: str = typer.Option("project", "--scope", help="project/global/all"),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Comma-separated statuses; default is active,ai_review,pending",
    ),
    page_size: int = typer.Option(100, "--page-size", help="Page size"),
    cursor: int | None = typer.Option(None, "--cursor", help="Pagination cursor"),
    include_protected: bool = typer.Option(True, "--include-protected/--no-protected"),
) -> None:
    """Fetch sleep candidates as JSON."""
    client = HubClient(Config.load())
    payload = {
        "project_id": project_id,
        "session_id": session_id,
        "scope": scope,
        "page_size": page_size,
        "cursor": cursor,
        "include_protected": include_protected,
    }
    if status:
        payload["status"] = [s.strip() for s in status.split(",") if s.strip()]
    try:
        result = client.sleep_candidates(payload)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    console.print_json(json.dumps(result, ensure_ascii=False))


@sleep_app.command("submit")
def submit(
    session_id: str = typer.Argument(..., help="Sleep session ID"),
    plan_file: Path = typer.Argument(..., help="JSON plan file"),
    text_file: Path | None = typer.Option(None, "--text", help="Optional text proposal file"),
) -> None:
    """Submit a client-generated sleep proposal."""
    client = HubClient(Config.load())
    try:
        json_proposal = json.loads(plan_file.read_text())
        text_proposal = text_file.read_text() if text_file else None
        result = client.sleep_submit_proposal(
            session_id,
            {
                "text_proposal": text_proposal,
                "json_proposal": json_proposal,
            },
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    console.print_json(json.dumps(result, ensure_ascii=False))


@sleep_app.command("apply")
def apply(
    session_id: str = typer.Argument(..., help="Sleep session ID"),
) -> None:
    """Apply an approved sleep proposal."""
    client = HubClient(Config.load())
    try:
        result = client.sleep_apply(session_id, approved=True)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    console.print_json(json.dumps(result, ensure_ascii=False))
