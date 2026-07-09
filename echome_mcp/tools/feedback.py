"""Memory feedback MCP tools."""

import json
from typing import Any

from echome_mcp.hub_client import MCPHubClient

VALID_RATINGS = {"helpful", "irrelevant", "outdated", "conflicting", "wrong", "important"}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_USED_BY = {"ai", "user", "system"}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    rating = str(item.get("rating", "")).strip().lower()
    confidence = str(item.get("confidence", "medium")).strip().lower()
    used_by = str(item.get("used_by", "ai")).strip().lower()
    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of: {', '.join(sorted(VALID_RATINGS))}")
    if confidence not in VALID_CONFIDENCE:
        confidence = "medium"
    if used_by not in VALID_USED_BY:
        used_by = "ai"

    return {
        "memory_id": item["memory_id"],
        "rating": rating,
        "note": item.get("note"),
        "task_context": item.get("task_context"),
        "used_by": used_by,
        "confidence": confidence,
        "source": "mcp",
    }


async def echome_memory_feedback(
    memory_id: str,
    rating: str,
    note: str | None = None,
    task_context: str | None = None,
    used_by: str = "ai",
    confidence: str = "medium",
) -> str:
    """Record one memory usefulness feedback signal."""
    client = MCPHubClient()
    try:
        payload = _normalize_item(
            {
                "memory_id": memory_id,
                "rating": rating,
                "note": note,
                "task_context": task_context,
                "used_by": used_by,
                "confidence": confidence,
            }
        )
        result = await client.create_memory_feedback(payload)
    except Exception as e:
        return f"Error recording memory feedback: {e}"

    return "Memory feedback recorded.\n\n" + _json(result)


async def echome_memory_feedback_batch(items: list[dict[str, Any]]) -> str:
    """Record several memory usefulness feedback signals."""
    client = MCPHubClient()
    try:
        payload = [_normalize_item(item) for item in items]
        result = await client.create_memory_feedback_batch(payload)
    except Exception as e:
        return f"Error recording memory feedback batch: {e}"

    return "Memory feedback batch recorded.\n\n" + _json(result)
