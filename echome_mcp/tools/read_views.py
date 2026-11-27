"""Explicit reading views: previews are never substitutes for complete source text.

Only known narrative fields are projected. Conditions, links, version metadata and
warnings are retained; REST payloads and explicit full reads are left untouched.
"""

import json
from copy import deepcopy
from typing import Any

PREVIEW_CHARS = 180
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
NARRATIVE_FIELDS = {
    "body_md",
    "content_text",
    "statement_md",
    "summary",
    "personal_note",
    "description",
    "resolution_note",
    "application_note",
    "explanation",
    "checks",
    "note",
}


def check_view(view: str) -> None:
    if view not in {"compact", "full"}:
        raise ValueError("view must be compact or full")


def page_options(data: dict[str, Any]) -> tuple[int, int]:
    offset, limit = data.get("offset", 0), data.get("limit", DEFAULT_LIMIT)
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("limit must be an integer between 1 and 100")
    return offset, limit


def pagination(total: int, offset: int, count: int, limit: int) -> dict[str, Any]:
    next_offset = offset + count if offset + count < total else None
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "complete": next_offset is None,
    }


def knowledge_record_index(record: dict[str, Any]) -> dict[str, Any]:
    """Keep safety/identity fields verbatim; identify every omitted narrative field."""
    if not isinstance(record.get("data"), dict) or not record.get("id"):
        return deepcopy(record)
    result = deepcopy(record)
    data = result["data"]
    previews: dict[str, str] = {}
    omitted: dict[str, int] = {}
    for field in NARRATIVE_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            continue
        # A short summary/statement is already useful, complete discovery text.
        if field in {"summary", "statement_md"} and len(value) <= PREVIEW_CHARS:
            continue
        previews[field] = value[:PREVIEW_CHARS]
        omitted["data." + field] = len(value)
        del data[field]
    for name, items in (
        ("data.evidence", data.get("evidence")),
        ("evidence_checks", result.get("evidence_checks")),
    ):
        if not isinstance(items, list):
            continue
        for index, evidence in enumerate(items):
            if not isinstance(evidence, dict):
                continue
            quote = evidence.get("quote")
            if isinstance(quote, str) and quote:
                omitted[f"{name}.{index}.quote"] = len(quote)
                evidence["quote_chars"] = len(quote)
                evidence["needs_expansion"] = True
                del evidence["quote"]
    arguments: dict[str, Any] = {
        "action": "get",
        "record_id": record["id"],
        "view": "full",
    }
    if record.get("revision") is not None:
        arguments["data"] = {"revision": record["revision"]}
    result.update(
        view="compact",
        needs_expansion=bool(omitted),
        read={"tool": "echome_knowledge_read", "arguments": arguments},
    )
    if previews:
        result["previews"] = previews
    if omitted:
        result["omitted_fields"] = omitted
    # Small records are already economical. Projection metadata must never make
    # them larger, or turn an already complete sentence into an extra read.
    original_chars = len(json.dumps(record, ensure_ascii=False))
    saved_chars = original_chars - len(json.dumps(result, ensure_ascii=False))
    if not omitted or saved_chars < max(256, original_chars * 0.2):
        return deepcopy(record)
    return result


def knowledge_warning_refs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep alerts discoverable even when their record is on another index page."""
    result = []
    for row in records:
        if not row.get("warnings") and row.get("kind") != "review":
            continue
        ref = {
            key: value
            for key, value in row.items()
            if key
            in {
                "id",
                "kind",
                "revision",
                "current_revision",
                "status",
                "current_status",
                "review_state",
                "reusable",
                "warnings",
            }
        }
        ref["read"] = {
            "tool": "echome_knowledge_read",
            "arguments": {
                "action": "get",
                "record_id": row["id"],
                "view": "full",
                "data": {"revision": row["revision"]},
            },
        }
        result.append(ref)
    return result


def knowledge_view(payload: dict[str, Any], action: str, data: dict[str, Any]) -> dict[str, Any]:
    if "error" in payload:
        return payload
    if action == "get":
        return knowledge_record_index(payload)
    result = deepcopy(payload)
    if action in {"list", "query", "backlinks"} and isinstance(result.get("items"), list):
        items = result["items"]
        offset, limit = page_options(data)
        if action == "backlinks":
            result["warning_refs"] = knowledge_warning_refs(items)
            result.update(
                pagination(len(items), offset, len(items[offset : offset + limit]), limit)
            )
            items = items[offset : offset + limit]
        result["items"] = [knowledge_record_index(item) for item in items]
        if any(item.get("needs_expansion") for item in result["items"]):
            result["view"] = "compact"
            result["content_complete"] = False
            result["notice"] = (
                "Pagination completeness covers the record index, not omitted text. Expand required records before reuse."
            )
    elif action == "context" and isinstance(result.get("records"), list):
        offset, limit = page_options(data)
        # Preserve the distinction between current records and pinned versions,
        # while applying one continuation offset across both collections.
        records, pinned = result["records"], result.get("pinned_versions", [])
        combined = [("records", row) for row in records] + [
            ("pinned_versions", row) for row in pinned
        ]
        selected = combined[offset : offset + limit]
        result["warning_refs"] = knowledge_warning_refs([row for _, row in combined])
        result["records"] = [
            knowledge_record_index(row) for name, row in selected if name == "records"
        ]
        result["pinned_versions"] = [
            knowledge_record_index(row) for name, row in selected if name == "pinned_versions"
        ]
        result.update(pagination(len(combined), offset, len(selected), limit))
        result["view"] = "compact"
        result["content_complete"] = False
        result["notice"] = (
            "Context index only. Follow next_offset; Hub truncation and omitted_fields still apply. Expand required records at their pinned revision before reuse."
        )
    return result


def scene_entry_index(entry: dict[str, Any], selector: str) -> dict[str, Any]:
    result = deepcopy(entry)
    result.pop("created_at", None)
    result.pop("updated_at", None)
    if result.get("origin_entry_id") is None:
        result.pop("origin_entry_id", None)
    content = result.pop("content", "")
    result["preview"] = content[:PREVIEW_CHARS]
    result["content_chars"] = len(content)
    validations = result.pop("validations", [])
    result["validation_refs"] = [
        {
            key: value
            for key, value in validation.items()
            if key in {"executed_at", "session_id", "evidence_ref", "result"}
        }
        for validation in validations
    ]
    if not result["validation_refs"]:
        del result["validation_refs"]
    result["needs_expansion"] = True
    result["read"] = {
        "tool": "echome_scene_read",
        "arguments": {
            "action": "get", "selector": selector, "entry_id": entry.get("id"), "view": "compact",
        },
    }
    if entry.get("status") == "archived":
        result["read"]["arguments"]["include_archived"] = True
    return result


def scene_safety_refs(entries: list[dict[str, Any]], selector: str) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in scene_entry_index(entry, selector).items()
            if key in {"id", "key", "category", "status", "revision", "read", "needs_expansion"}
        }
        for entry in entries
        if entry.get("category") == "caution" or entry.get("status") == "needs_review"
    ]


def scene_view(payload: dict[str, Any], selector: str, offset: int, limit: int) -> dict[str, Any]:
    if "error" in payload or not isinstance(payload.get("entries"), list):
        return payload
    result = deepcopy(payload)
    entries = result["entries"]
    result.pop("markdown", None)
    result["entries"] = [
        scene_entry_index(entry, selector) for entry in entries[offset : offset + limit]
    ]
    result.update(pagination(len(entries), offset, len(result["entries"]), limit))
    result["view"] = "compact"
    result["needs_expansion"] = bool(entries)
    result["content_complete"] = False
    result["caution_count"] = sum(entry.get("category") == "caution" for entry in entries)
    result["needs_review_count"] = sum(entry.get("status") == "needs_review" for entry in entries)
    result["safety_refs"] = scene_safety_refs(entries, selector)
    result["notice"] = (
        "Entry index only; previews can omit conditions and prohibitions. Read relevant entries and scene cautions in full before acting; follow next_offset for the rest of the index. Active status alone does not validate an SOP."
    )
    result["read"] = {
        "tool": "echome_scene_read",
        "arguments": {"action": "get", "selector": selector, "view": "full"},
    }
    return result
