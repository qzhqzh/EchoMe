"""Manage explicitly selected scenarios and continuing items from the CLI."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import typer
from rich.console import Console

from echome.core.client import HubClient

scenario_app = typer.Typer(help="Versioned repeatable scenarios and continuing items")
console = Console()


def _segment(value: str) -> str:
    if not value or "/" in value or ".." in value:
        raise typer.BadParameter("Invalid identifier")
    return quote(value, safe="")


def _file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"Cannot read JSON file: {exc}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("JSON file must contain an object")
    return payload


def _json_option(value: str) -> dict[str, str]:
    try:
        payload = json.loads(value)
    except ValueError as exc:
        raise typer.BadParameter("Expected a JSON object") from exc
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in payload.items()
    ):
        raise typer.BadParameter("Expected a JSON object of strings")
    return payload


def _call(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    try:
        result = HubClient().scenario_request(method, path, data, params)
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        console.print(
            f"[red]Hub returned {exc.response.status_code}:[/red] {detail or 'request failed'}"
        )
        raise typer.Exit(1) from exc
    except httpx.RequestError as exc:
        console.print(f"[red]Hub unavailable:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print_json(data=result)


@scenario_app.command("list")
def list_scenarios() -> None:
    """List stored scenario identities."""
    _call("GET", "")


@scenario_app.command("show")
def show(slug: str) -> None:
    """Show every version of one scenario."""
    _call("GET", f"/catalog/{_segment(slug)}")


@scenario_app.command("create")
def create(file: Path) -> None:
    """Create a draft scenario from a JSON definition file."""
    _call("POST", "", _file(file))


@scenario_app.command("new-version")
def new_version(slug: str, file: Path) -> None:
    """Add an immutable draft version from a JSON file containing definition."""
    _call("POST", f"/catalog/{_segment(slug)}/versions", _file(file))


@scenario_app.command("publish")
def publish(slug: str, version: int, evidence: str = typer.Option(..., "--evidence")) -> None:
    """Publish a version after a real validation result is available."""
    _call(
        "POST",
        f"/catalog/{_segment(slug)}/versions/{version}/publish",
        {"validation_evidence": evidence},
    )


@scenario_app.command("activate")
def activate(slug: str, version: int) -> None:
    """Make a previously published version the default."""
    _call("POST", f"/catalog/{_segment(slug)}/versions/{version}/activate")


@scenario_app.command("disable")
def disable(slug: str) -> None:
    """Stop new items and explicit routing for a scenario."""
    _call("PATCH", f"/catalog/{_segment(slug)}", {"enabled": False})


@scenario_app.command("resolve")
def resolve(
    selector: str,
    parameters: str = typer.Option("{}", "--parameters", help="Non-secret JSON string map"),
    environment: str = typer.Option("{}", "--environment", help="JSON string map"),
) -> None:
    """Resolve an explicit scenario ID or alias and inspect applicability."""
    _call(
        "POST",
        "/resolve",
        {
            "selector": selector,
            "parameters": _json_option(parameters),
            "environment": _json_option(environment),
        },
    )


@scenario_app.command("start")
def start(file: Path) -> None:
    """Create a one-off or continuous item from a JSON file."""
    _call("POST", "/items", _file(file))


@scenario_app.command("items")
def items(
    status: str | None = None,
    mode: str | None = None,
    query: str | None = typer.Option(None, "--query"),
    scenario: str | None = typer.Option(None, "--scenario"),
) -> None:
    """List items, optionally narrowing by title, goal, or exact scenario ID."""
    _call(
        "GET",
        "/items",
        params={"status": status, "mode": mode, "query": query, "scenario_slug": scenario},
    )


@scenario_app.command("due")
def due() -> None:
    """List continuous items whose next check is due."""
    _call("GET", "/due")


@scenario_app.command("item")
def item(item_id: str) -> None:
    """Show one item and its pinned scenario version."""
    _call("GET", f"/items/{_segment(item_id)}")


@scenario_app.command("set-status")
def set_status(
    item_id: str,
    status: str = typer.Argument(..., help="active, paused, or completed"),
    revision: int = typer.Option(..., "--revision"),
) -> None:
    """Pause, resume, or complete an item using its current revision."""
    if status not in {"active", "paused", "completed"}:
        raise typer.BadParameter("status must be active, paused, or completed")
    _call("PATCH", f"/items/{_segment(item_id)}", {"expected_revision": revision, "status": status})


@scenario_app.command("upgrade")
def upgrade(
    item_id: str,
    version: int,
    revision: int = typer.Option(..., "--revision"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    """Explicitly switch an item to another published scenario version."""
    _call(
        "POST",
        f"/items/{_segment(item_id)}/upgrade",
        {
            "expected_revision": revision,
            "version": version,
            "reason": reason,
        },
    )


@scenario_app.command("bind")
def bind(
    item_id: str,
    slug: str,
    revision: int = typer.Option(..., "--revision"),
    reason: str = typer.Option(..., "--reason"),
    version: int | None = typer.Option(None, "--version"),
    parameters: str | None = typer.Option(None, "--parameters", help="Non-secret JSON string map"),
    environment: str | None = typer.Option(None, "--environment", help="JSON string map"),
) -> None:
    """Bind a standalone item to a published scenario version."""
    _call(
        "POST",
        f"/items/{_segment(item_id)}/bind",
        {
            "expected_revision": revision,
            "scenario_slug": slug,
            "version": version,
            "reason": reason,
            "parameters": _json_option(parameters) if parameters is not None else None,
            "environment": _json_option(environment) if environment is not None else None,
        },
    )


@scenario_app.command("claim")
def claim(
    item_id: str,
    key: str = typer.Option(..., "--key", help="Unique execution attempt key"),
    force: bool = False,
) -> None:
    """Claim one execution lease before performing the procedure."""
    _call("POST", f"/items/{_segment(item_id)}/claim", {"idempotency_key": key, "force": force})


@scenario_app.command("finish")
def finish(item_id: str, run_id: str, file: Path) -> None:
    """Finish a claimed run using a JSON result file with its lease token."""
    _call("POST", f"/items/{_segment(item_id)}/runs/{_segment(run_id)}/finish", _file(file))


@scenario_app.command("runs")
def runs(item_id: str) -> None:
    """Show recent execution attempts for an item."""
    _call("GET", f"/items/{_segment(item_id)}/runs")
