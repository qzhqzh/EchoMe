"""Focused card browsing and bounded AI edits over the existing Memory model."""

import json
import re
import uuid
from typing import Any

from echome_mcp.hub_client import MCPHubClient

CARD_SPECS: dict[str, dict[str, Any]] = {
    "habit": {
        "tag": "card:habit",
        "type": "style",
        "layer": "L1",
        "priority": 7,
        "fields": {
            "when": ("适用时机", "When"),
            "do": ("执行习惯", "Do"),
            "avoid": ("不要做", "Avoid"),
        },
        "required": {"when", "do"},
    },
    "skill": {
        "tag": "card:skill",
        "type": "method",
        "layer": "L2",
        "priority": 5,
        "fields": {
            "when": ("适用任务", "Use when"),
            "do": ("操作步骤", "Steps"),
            "avoid": ("不要做", "Avoid"),
            "verify": ("验证方式", "Verify"),
        },
        "required": {"when", "do", "verify"},
    },
    "knowledge": {
        "tag": "card:knowledge",
        "type": "reasoning",
        "layer": "L2",
        "priority": 5,
        "fields": {
            "claim": ("核心结论", "Claim"),
            "applies_when": ("适用条件", "Applies when"),
            "avoid": ("避免误用", "Avoid misuse"),
            "evidence": ("依据或来源", "Evidence"),
        },
        "required": {"claim", "applies_when", "evidence"},
    },
}


def _kind(kind: str) -> dict[str, Any]:
    if kind not in CARD_SPECS:
        raise ValueError("kind must be habit, skill, or knowledge")
    return CARD_SPECS[kind]


def _one_line(value: str, *, max_length: int = 2000) -> str:
    if not isinstance(value, str):
        raise ValueError("Card fields must be strings")
    clean = re.sub(r"\s*[\r\n]+\s*", "；", value.strip())
    if len(clean) > max_length:
        raise ValueError(f"Card field exceeds {max_length} characters")
    return clean


def _format_steps(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Card fields must be strings")
    parts = re.split(r"(?:\r?\n|[；;]\s*(?=\d+[.)]\s*))", value.strip())
    steps = [re.sub(r"^(?:\d+[.)]|[-*])\s*", "", part.strip()).strip() for part in parts]
    steps = [step for step in steps if step]
    if len(steps) > 6:
        raise ValueError("A skill card can contain at most 6 steps; split longer procedures")
    formatted = "；".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    if len(formatted) > 1200:
        raise ValueError("Skill steps exceed 1200 characters")
    return formatted


def _validate_fields(kind: str, fields: dict[str, str], *, creating: bool) -> dict[str, str]:
    spec = _kind(kind)
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object")
    unexpected = fields.keys() - spec["fields"].keys()
    if unexpected:
        raise ValueError(f"Unknown {kind} card fields: {', '.join(sorted(unexpected))}")
    limits = {"when": 400, "do": 500, "avoid": 500, "verify": 500,
              "claim": 500, "applies_when": 400, "evidence": 500}
    cleaned = {
        key: _format_steps(value) if kind == "skill" and key == "do"
        else _one_line(value, max_length=limits[key])
        for key, value in fields.items()
    }
    if any(not value for value in cleaned.values()):
        raise ValueError("Card fields cannot be blank; use the Web console to remove a rule")
    if creating:
        missing = spec["required"] - cleaned.keys()
        if missing:
            raise ValueError(f"Missing required {kind} card fields: {', '.join(sorted(missing))}")
    return cleaned


def _line_matches(line: str, names: tuple[str, str]) -> bool:
    stripped = line.strip().lower()
    return any(
        stripped.startswith(f"{name.lower()}{separator}")
        for name in names
        for separator in ("：", ":")
    )


def _field_value(content: str, names: tuple[str, str]) -> str:
    for line in content.splitlines():
        if _line_matches(line, names):
            return re.split(r"[:：]", line.strip(), maxsplit=1)[1].strip()
    return ""


def _replace_line(lines: list[str], names: tuple[str, str], value: str) -> None:
    replacement = f"{names[0]}：{value}"
    for index, line in enumerate(lines):
        if _line_matches(line, names):
            lines[index] = replacement
            return
    lines.append(replacement)


def _card_summary(item: dict[str, Any], kind: str, *, compact: bool = False) -> dict[str, Any]:
    spec = _kind(kind)
    content = item.get("content", "")
    fields = {key: _field_value(content, names) for key, names in spec["fields"].items()}
    if compact:
        fields = {key: value[:220] + ("…" if len(value) > 220 else "") for key, value in fields.items()}
    return {
        "id": item["id"],
        "kind": kind,
        "title": item["title"],
        "status": item["status"],
        "updated_at": item["updated_at"],
        "scope": item.get("scope"),
        "fields": fields,
    }


def _check_id(memory_id: str) -> str:
    try:
        return str(uuid.UUID(memory_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("memory_id must be a UUID") from exc


async def echome_card_read(
    action: str,
    kind: str | None = None,
    memory_id: str | None = None,
    query: str | None = None,
    status: str = "available",
    project: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List concise cards or read one full card with its revision and scope."""
    client = MCPHubClient()
    if action == "get":
        if not memory_id:
            raise ValueError("memory_id is required for get")
        item = await client.get_memory(_check_id(memory_id))
        kinds = [name for name, spec in CARD_SPECS.items() if spec["tag"] in item.get("tags", [])]
        if not kinds or (kind is not None and kind not in kinds):
            raise ValueError("The memory is not a card of the requested kind")
        return json.dumps(
            {
                "card": item,
                "kinds": kinds,
                "fields": {name: _card_summary(item, name)["fields"] for name in kinds},
            },
            ensure_ascii=False,
        )
    if action != "list":
        raise ValueError("action must be list or get")
    if status not in {"available", "active", "ai_review", "archived"}:
        raise ValueError("status must be available, active, ai_review, or archived")
    if not 1 <= limit <= 50 or offset < 0:
        raise ValueError("limit must be 1-50 and offset must be nonnegative")
    if query and len(query) > 200:
        raise ValueError("query is too long")
    names = [kind] if kind else list(CARD_SPECS)
    results = {}
    for name in names:
        spec = _kind(name)
        page = await client.list_cards(
            spec["tag"],
            None if status == "available" else status,
            query=query,
            limit=limit,
            offset=offset,
            project=project,
        )
        results[name] = {
            "total": page["total"],
            "items": [_card_summary(item, name, compact=True) for item in page["items"]],
        }
    return json.dumps({"status": status, "categories": results}, ensure_ascii=False)


async def echome_card_write(
    action: str,
    kind: str,
    basis: str,
    title: str | None = None,
    fields: dict[str, str] | None = None,
    project: str | None = None,
    memory_id: str | None = None,
    expected_updated_at: str | None = None,
) -> str:
    """Create an AI-reviewed card or update only named lines of an existing card."""
    spec = _kind(kind)
    evidence = _one_line(basis, max_length=400)
    if not evidence:
        raise ValueError("basis must identify the user instruction or concrete source evidence")
    cleaned_title = _one_line(title, max_length=100) if title is not None else None
    if title is not None and not cleaned_title:
        raise ValueError("title cannot be blank")
    cleaned_fields = _validate_fields(kind, fields or {}, creating=action == "create")
    client = MCPHubClient()

    if action == "create":
        if not cleaned_title:
            raise ValueError("title is required for create")
        canonical_project = None
        if project:
            found = await client.get_project(project)
            if not found or not found.get("id"):
                raise ValueError("Existing canonical project not found; card was not created")
            canonical_project = found["id"]
        # Exact-title reuse is enforced; agents should also inspect nearby cards before creating.
        for existing_status in (None, "archived"):
            page = await client.list_cards(
                spec["tag"], existing_status, query=cleaned_title, limit=50
            )
            for item in page["items"]:
                scope = item.get("scope") or {}
                same_scope = (
                    canonical_project in scope.get("projects", [])
                    if canonical_project
                    else bool(scope.get("global", True))
                )
                if (
                    same_scope
                    and re.sub(r"\s+", "", item["title"]).casefold()
                    == re.sub(r"\s+", "", cleaned_title).casefold()
                ):
                    return json.dumps(
                        {
                            "status": "already_exists",
                            "id": item["id"],
                            "existing_status": item["status"],
                            "title": item["title"],
                        },
                        ensure_ascii=False,
                    )
        lines = [
            f"{names[0]}：{cleaned_fields[key]}"
            for key, names in spec["fields"].items()
            if key in cleaned_fields
        ]
        lines.append(f"建卡依据：{evidence}")
        payload = {
            "title": cleaned_title,
            "content": "\n\n".join(lines),
            "type": spec["type"],
            "layer": spec["layer"],
            "priority": spec["priority"],
            "tags": [spec["tag"]],
            "status": "ai_review",
            "source": "ai_suggested",
            "scope": {
                "global": canonical_project is None,
                "projects": [canonical_project] if canonical_project else [],
                "exclude_projects": [],
            },
        }
        created = await client.create_memory(payload)
        return json.dumps(
            {
                "status": "created",
                "review_status": "ai_review",
                "id": created["id"],
                "kind": kind,
                "title": cleaned_title,
            },
            ensure_ascii=False,
        )

    if action == "edit":
        if not memory_id or not expected_updated_at:
            raise ValueError(
                "memory_id and expected_updated_at from echome_card_read(get) are required for edit"
            )
        if not cleaned_fields and cleaned_title is None:
            raise ValueError("Provide at least one field or a title to edit")
        item = await client.get_memory(_check_id(memory_id))
        if spec["tag"] not in item.get("tags", []):
            raise ValueError("The memory is not a card of the requested kind")
        if item["status"] not in {"active", "ai_review"}:
            raise ValueError("Only active or ai_review cards can be edited")
        if item["updated_at"] != expected_updated_at:
            raise ValueError("Card changed since it was read; read the card again before editing")
        lines = item["content"].split("\n")
        for key, value in cleaned_fields.items():
            _replace_line(lines, spec["fields"][key], value)
        _replace_line(lines, ("最近调整依据", "Latest edit basis"), evidence)
        content = "\n".join(lines)
        patch = {"content": content, "expected_updated_at": expected_updated_at}
        if cleaned_title is not None:
            patch["title"] = cleaned_title
        updated = await client.patch_memory(item["id"], patch)
        return json.dumps(
            {
                "status": "updated",
                "id": updated["id"],
                "kind": kind,
                "title": updated["title"],
                "updated_at": updated["updated_at"],
            },
            ensure_ascii=False,
        )

    raise ValueError("action must be create or edit")
