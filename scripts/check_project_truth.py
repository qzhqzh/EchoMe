"""Fail CI when repository metadata and authoritative documentation disagree."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DOCS = (
    "README.md",
    "docs/roadmap.md",
    "docs/project-knowledge.md",
    "docs/memory-model.md",
    "docs/mcp-spec.md",
)


def _python_string(path: str, name: str) -> str:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    values: list[str] = []
    for node in ast.walk(tree):
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and target.id == name
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            values.append(value.value)
    if not values:
        raise ValueError(f"{path} has no literal {name}")
    return values[-1]


def _capabilities_version() -> str:
    path = "echome_mcp/tools/capabilities.py"
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and key.value == "capabilities_version"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                return value.value
    raise ValueError(f"{path} has no literal capabilities_version")


def _migration_value(path: Path, name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            return ast.literal_eval(value)
    raise ValueError(f"{path.relative_to(ROOT)} has no {name}")


def _alembic_heads() -> set[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted((ROOT / "hub/alembic/versions").glob("*.py")):
        revision = _migration_value(path, "revision")
        down_revision = _migration_value(path, "down_revision")
        revisions.add(str(revision))
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, tuple | list):
            parents.update(str(item) for item in down_revision if item is not None)
    return revisions - parents


def _project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def _locked_version() -> str:
    payload = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in payload["package"] if item["name"] == "echome")
    return str(package["version"])


def check_project_truth() -> list[str]:
    errors: list[str] = []
    version = _project_version()
    heads = _alembic_heads()
    if len(heads) != 1:
        errors.append(f"expected one Alembic head, found {sorted(heads)}")
        head = "<multiple>"
    else:
        head = next(iter(heads))
    capabilities = _capabilities_version()

    metadata_versions = {
        "uv.lock": _locked_version(),
        "echome/__init__.py": _python_string("echome/__init__.py", "__version__"),
        "echome_mcp/__init__.py": _python_string(
            "echome_mcp/__init__.py", "__version__"
        ),
        "hub/app/core/config.py": _python_string("hub/app/core/config.py", "app_version"),
    }
    for path, actual in metadata_versions.items():
        if actual != version:
            errors.append(f"{path} version {actual!r} != pyproject.toml {version!r}")

    required_snippets = {
        "README.md": (
            f"当前稳定版本为 **v{version}**",
            f"当前生产 schema revision 为 `{head}`",
        ),
        "docs/roadmap.md": (
            f"**当前稳定版本**：`echome v{version}`",
            f"**当前生产 schema**：revision `{head}`",
        ),
        "docs/project-knowledge.md": (
            f"current deployed application version is `{version}`",
            f"current production Alembic revision is `{head}`",
        ),
        "docs/mcp-spec.md": (f"`{capabilities}`",),
    }
    for path, snippets in required_snippets.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                errors.append(f"{path} is missing current-truth marker: {snippet}")

    forbidden = {
        "docs/memory-model.md": (
            "push/pull 使用 last-write-wins",
            "ai_review 记忆立即参与后续检索，但不默认参与 Memory Sleep",
        ),
        "README.md": (
            "当前生产 schema revision 为 `015`",
        ),
        "docs/project-knowledge.md": (
            "010 -> 012 -> 010 -> 012",
            "run Alembic upgrade to `012`",
        ),
    }
    for path, snippets in forbidden.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet in text:
                errors.append(f"{path} contains stale current guidance: {snippet}")

    current_version_claim = re.compile(
        r"当前稳定版本(?:为|[：:])\s*(?:\*\*)?`?v?(\d+\.\d+\.\d+)"
    )
    current_schema_claim = re.compile(
        r"当前(?:生产)?(?:数据库|\s*schema).*?(?:revision\s*(?:为|[：:])?|为)\s*`?(\d{3})`?",
        re.IGNORECASE,
    )
    for path in AUTHORITATIVE_DOCS:
        text = (ROOT / path).read_text(encoding="utf-8")
        for claimed in current_version_claim.findall(text):
            if claimed != version:
                errors.append(f"{path} claims current version {claimed}, expected {version}")
        for claimed in current_schema_claim.findall(text):
            if claimed != head:
                errors.append(f"{path} claims current schema {claimed}, expected {head}")
    return errors


def main() -> int:
    try:
        errors = check_project_truth()
    except (KeyError, StopIteration, SyntaxError, TypeError, ValueError) as exc:
        print(f"project truth check could not run: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Project truth drift detected:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Project truth check passed: "
        f"version={_project_version()}, alembic_head={next(iter(_alembic_heads()))}, "
        f"capabilities={_capabilities_version()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
