"""Validate current guides against installed CLI/MCP or Hub contracts, without I/O calls."""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import io
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CURRENT_DOCS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "docs/api-spec.md",
    "docs/mcp-spec.md",
    "docs/user-guide.md",
    "docs/memory-model.md",
    "docs/memory-guide.md",
    "docs/memory-retrieval.md",
    "docs/deployment.md",
    "docs/roadmap.md",
    "docs/development-priorities.md",
    "docs/dsh-integration.md",
    "docs/development-checks.md",
)
FENCE = re.compile(r"^```(\w*)[^\n]*\n(.*?)^```\s*$", re.M | re.S)
ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE) (/[^\s`|（）)]+)")


def normalized_route(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.removeprefix("/api/v1").split("?")[0])


def check_links(path: Path, text: str) -> list[str]:
    errors = []
    # Code fences can contain example links which aren't repository navigation.
    prose = FENCE.sub("", text)
    for target in re.findall(r"\]\(([^)]+)\)", prose):
        target = target.strip("<>").split("#")[0]
        if not target or re.match(r"[a-z]+:", target) or target.startswith("/"):
            continue
        if not (path.parent / target).exists():
            errors.append(f"{path.name}: missing relative link {target}")
    return errors


def check_command(line: str) -> None:
    """Parse command/option syntax; never invoke a CLI callback or command."""
    import click
    from typer.main import get_command

    from echome.main import app

    tokens = shlex.split(line, comments=True)
    if not tokens or tokens[0] not in {"echome", "eme"}:
        return
    command = get_command(app)
    args = tokens[1:]
    while True:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                context = command.make_context("echome", args)
        except click.exceptions.Exit as exc:
            if exc.exit_code == 0:
                return
            raise
        with context:
            if not isinstance(command, click.Group):
                return
            # Click <=8 stores a group's command separately; Click 9 moves it
            # into args. Avoid the deprecated protected_args property.
            remaining = [*getattr(context, "_protected_args", []), *context.args]
            if not remaining:
                return
            name, args = remaining[0], remaining[1:]
            child = command.get_command(context, name)
            if child is None:
                raise ValueError(f"unknown CLI command {name}")
            command = child


def check_mcp_schema(
    documented: dict[str, Any], actual: dict[str, Any], path="inputSchema"
) -> None:
    """Docs may omit optional details, but any stated constraint must be true."""
    for key, value in documented.items():
        if key in {"description", "title", "examples"}:
            continue
        if key not in actual:
            raise ValueError(f"{path}.{key} is not in the current tool schema")
        if isinstance(value, dict):
            check_mcp_schema(value, actual[key], f"{path}.{key}")
        elif key in {"enum", "required"}:
            if set(value) != set(actual[key]):
                raise ValueError(f"{path}.{key} differs: {value} != {actual[key]}")
        elif value != actual[key]:
            raise ValueError(f"{path}.{key} differs: {value} != {actual[key]}")


def check_docs(surface: str) -> list[str]:
    errors: list[str] = []
    mcp_tools: dict[str, Any] = {}
    api_routes: dict[tuple[str, str], Any] = {}
    if surface == "client":
        from echome_mcp.server import list_tools
        from echome_mcp.tools.remember import VALID_TYPES

        tree = ast.parse((ROOT / "hub/app/schemas/memory.py").read_text())
        memory_type = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MemoryType"
        )
        hub_types = {
            ast.literal_eval(node.value)
            for node in memory_type.body
            if isinstance(node, ast.Assign)
        }
        if hub_types != VALID_TYPES:
            errors.append("MCP remember types differ from Hub MemoryType")

        previous = os.environ.get("ECHOME_MCP_PROFILE")
        try:
            os.environ["ECHOME_MCP_PROFILE"] = "full"
            mcp_tools = {item.name: item for item in asyncio.run(list_tools())}
        finally:
            if previous is None:
                os.environ.pop("ECHOME_MCP_PROFILE", None)
            else:
                os.environ["ECHOME_MCP_PROFILE"] = previous
    else:
        sys.path.insert(0, str(ROOT / "hub"))
        from app.main import app
        from fastapi.routing import APIRoute

        for route in app.routes:
            if isinstance(route, APIRoute):
                for method in route.methods:
                    api_routes[method, normalized_route(route.path)] = route
    for relative in CURRENT_DOCS:
        path = ROOT / relative
        if not path.exists():
            errors.append(f"missing current guide {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        errors.extend(check_links(path, text))
        if surface == "hub" and relative == "docs/api-spec.md":
            declared = [
                pair
                for line in text.splitlines()
                if "不存在" not in line
                for pair in ROUTE.findall(line)
            ]
            declared += re.findall(
                r"\|\s*`?(GET|POST|PUT|PATCH|DELETE)`?\s*\|\s*`?(/[^`|\s]+)", text
            )
            for method, route in declared:
                if (method, normalized_route(route)) not in api_routes:
                    errors.append(f"{relative}: unknown route {method} {route}")
        for match in FENCE.finditer(text):
            language, source = match.groups()
            location = f"{relative}:{text[: match.start()].count(chr(10)) + 1}"
            try:
                if language in {"bash", "sh"} and surface == "client":
                    for line in source.replace("\\\n", " ").splitlines():
                        if re.match(r"^\s*(echome|eme)(\s|$)", line):
                            check_command(line)
                if language != "json":
                    continue
                payload = json.loads(source)
                before = text[: match.start()]
                annotation = re.search(r"<!-- echome-contract: mcp (\w+) -->\s*$", before)
                if surface == "client" and isinstance(payload, dict):
                    if "inputSchema" in payload and "name" in payload:
                        check_mcp_schema(
                            payload["inputSchema"], mcp_tools[payload["name"]].inputSchema
                        )
                    elif re.search(r"\*\*Input Schema\*\*:\s*$", before):
                        headings = re.findall(r"^### [\d.]+ (echome_\w+)", before, re.M)
                        check_mcp_schema(payload, mcp_tools[headings[-1]].inputSchema)
                    elif annotation:
                        from jsonschema import validate

                        tool = mcp_tools[annotation.group(1)]
                        schema = {**tool.inputSchema, "additionalProperties": False}
                        validate(payload, schema)
                if surface == "hub" and relative == "docs/api-spec.md":
                    section = re.split(r"^### ", before, flags=re.M)[-1]
                    route_match = ROUTE.match(section)
                    # Only immediate Request Body examples are input payloads.
                    request = re.search(r"\*\*Request Body\*\*:\s*$", section)
                    if route_match and request:
                        from pydantic import TypeAdapter

                        key = route_match.group(1), normalized_route(route_match.group(2))
                        route = api_routes[key]
                        if route.body_field is None:
                            raise ValueError("route has no request body")
                        model = route.body_field.field_info.annotation
                        unknown = set(payload) - {
                            field.alias or name for name, field in model.model_fields.items()
                        }
                        if unknown:
                            raise ValueError(f"unknown request fields: {sorted(unknown)}")
                        TypeAdapter(model).validate_python(payload)
            except Exception as exc:
                errors.append(f"{location}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=("client", "hub"), required=True)
    args = parser.parse_args()
    errors = check_docs(args.surface)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Documentation contracts passed ({args.surface}): {len(CURRENT_DOCS)} current guides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
