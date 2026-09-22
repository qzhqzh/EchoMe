"""Explicit, shadow-only entry point for memory interaction decisions."""

import asyncio
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from echome.core.memory_gate import GateRequest, GateSettings, decide

gate_app = typer.Typer(help="Evaluate memory interactions without reading or writing Hub memories.")
MAX_INPUT_BYTES = 65536


def read_request(input_path: Path | None) -> GateRequest:
    """Read a bounded JSON envelope; never echo invalid input in an error."""
    if input_path is None:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        with input_path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Gate input exceeds 64 KiB")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Gate input must be a UTF-8 JSON object") from exc
    return GateRequest.model_validate(payload)


def append_audit(path: Path, decision: dict[str, Any], event_id: str | None) -> None:
    """Append decision metadata only to a private, regular file."""
    record = {
        "schema_version": "echome.memory-gate-event.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "event_id": event_id,
        "decision": decision,
        "execution": "shadow_only",
    }
    encoded = (json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Audit destination must not be a symlink")
    flags = (
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Audit destination must be a regular file")
        if os.name != "nt" and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid()):
            raise ValueError("Audit file must be owned by this user with mode 600")
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("Incomplete audit write")
    finally:
        os.close(descriptor)


@gate_app.command("decide")
def decide_command(
    input_path: Annotated[
        Path | None, typer.Option("--input", help="JSON request file; omit to read standard input.")
    ] = None,
    provider: Annotated[str, typer.Option(help="rules, kev, or laya")] = "rules",
    base_url: Annotated[str | None, typer.Option(help="Explicit decision service URL")] = None,
    model: Annotated[str | None, typer.Option(help="Decision model identifier")] = None,
    api_key_env: Annotated[
        str, typer.Option(help="Environment variable containing the decision service key")
    ] = "ECHOME_GATE_API_KEY",
    timeout: Annotated[float, typer.Option(min=0.1, max=30.0)] = 2.0,
    threshold: Annotated[float, typer.Option(min=0.0, max=1.0)] = 0.8,
    audit: Annotated[
        Path | None, typer.Option(help="Optional private JSONL audit file; excludes request text")
    ] = None,
    event_id: Annotated[
        str | None, typer.Option(help="Optional opaque caller event ID; never put user text here")
    ] = None,
) -> None:
    """Return one JSON decision. This command never calls the Hub or saves a memory."""
    if event_id is not None and (
        not 1 <= len(event_id) <= 128
        or any(
            not (character.isascii() and (character.isalnum() or character in "-_.:"))
            for character in event_id
        )
    ):
        raise typer.BadParameter("event-id must be an opaque ID of at most 128 characters")
    try:
        request = read_request(input_path)
        settings = GateSettings.model_validate(
            {
                "provider": provider,
                "base_url": base_url,
                "model": model,
                "api_key": os.environ.get(api_key_env, ""),
                "timeout_seconds": timeout,
                "threshold": threshold,
            }
        )
    except ValidationError:
        raise typer.BadParameter("Invalid gate request or provider settings") from None
    except (OSError, ValueError):
        raise typer.BadParameter("Unable to read a valid, bounded JSON gate request") from None
    decision = asyncio.run(decide(request, settings)).model_dump(mode="json")
    if audit is not None:
        try:
            append_audit(audit, decision, event_id)
        except (OSError, ValueError):
            typer.echo("Could not append private gate audit; decision was not executed.", err=True)
            raise typer.Exit(1) from None
    typer.echo(json.dumps(decision, ensure_ascii=False, allow_nan=False))
