"""Opt-in local Codex adapter; hook errors always let the user's work continue."""

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from echome.hook_entry import MAX_INPUT_BYTES, handle

hook_app = typer.Typer(help="Manage the opt-in, read-only Codex memory adapter.")


@hook_app.command("codex")
def codex_hook(
    managed_by: Annotated[str, typer.Option(hidden=True)] = "echome-v1",
) -> None:
    """Consume a Codex hook envelope; emit bounded additionalContext or {}."""
    output = handle(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1), managed_by)
    typer.echo(json.dumps(output, ensure_ascii=False))


@hook_app.command("install")
def install(
    target_dir: Annotated[Path | None, typer.Option(help="Codex configuration directory")] = None,
    executable: Annotated[
        Path | None, typer.Option(help="Absolute installed echome executable")
    ] = None,
) -> None:
    from echome.core.hook_install import install_hooks

    try:
        result = install_hooks(target_dir or Path.home() / ".codex", executable=executable)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter("Unable to safely update hook configuration") from exc
    typer.echo(json.dumps(result, ensure_ascii=False, default=str))
    typer.echo("Review and trust the EchoMe hooks in Codex /hooks, then open or resume a session.")


@hook_app.command("remove")
def remove(target_dir: Annotated[Path | None, typer.Option()] = None) -> None:
    from echome.core.hook_install import remove_hooks

    try:
        result = remove_hooks(target_dir or Path.home() / ".codex")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter("Unable to safely update hook configuration") from exc
    typer.echo(json.dumps(result, ensure_ascii=False, default=str))


@hook_app.command("status")
def status(target_dir: Annotated[Path | None, typer.Option()] = None) -> None:
    from echome.core.hook_install import hook_status

    try:
        result = hook_status(target_dir or Path.home() / ".codex")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter("Unable to inspect hook configuration") from exc
    typer.echo(json.dumps(result, ensure_ascii=False, default=str))
