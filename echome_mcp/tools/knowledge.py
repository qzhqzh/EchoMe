"""Explicit, bounded knowledge operations. Consequential reviewer actions are not tools."""

import json
from typing import Any
from uuid import UUID

import httpx

from echome_mcp.hub_client import MCPHubClient
from echome_mcp.tools.read_views import check_view, knowledge_view, page_options


async def _request(
    method: str, path: str, data: dict[str, Any] | None = None, params: dict[str, Any] | None = None
) -> str:
    try:
        payload = await MCPHubClient().knowledge_request(method, path, data, params)
        return json.dumps(payload, ensure_ascii=False)
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        return json.dumps(
            {
                "schema_version": "echome.error.v1",
                "error": {
                    "code": "KNOWLEDGE_REQUEST_FAILED",
                    "status": exc.response.status_code,
                    "message": detail or "Knowledge request failed",
                },
            },
            ensure_ascii=False,
        )


async def echome_knowledge_read(
    action: str,
    record_id: str | None = None,
    data: dict[str, Any] | None = None,
    view: str = "full",
) -> str:
    """Preserve full reads by default; compact indexes are an explicit option."""
    check_view(view)
    data = dict(data or {})
    if action == "schema":
        return await _request("GET", "/schema")
    if view == "compact" and action in {"list", "query", "backlinks", "context"}:
        offset, limit = page_options(data)
        if action in {"list", "query"}:
            data.setdefault("limit", limit)
    if action == "list":
        raw = await _request("GET", "/records", params=data)
    elif action == "query":
        raw = await _request("POST", "/query", data=data)
    else:
        if action not in ("get", "history", "backlinks", "context"):
            raise ValueError("Unknown knowledge read action")
        if not record_id:
            raise ValueError("record_id is required")
        path = "/records/" + str(UUID(record_id))
        if action != "get":
            path += "/" + action
        params = {
            key: value
            for key, value in data.items()
            if view != "compact"
            or action not in {"context", "backlinks"}
            or key not in {"offset", "limit"}
        }
        raw = await _request("GET", path, params=params)
    if view == "full" or action == "history":
        return raw
    return json.dumps(knowledge_view(json.loads(raw), action, data), ensure_ascii=False)


async def echome_knowledge_write(
    action: str, data: dict[str, Any], record_id: str | None = None
) -> str:
    """Create or revise one typed object. Read schema, then use expected_revision."""
    if action == "create":
        return await _request("POST", "/records", data=data)
    if action == "update":
        if not record_id:
            raise ValueError("record_id is required for update")
        return await _request("PATCH", "/records/" + str(UUID(record_id)), data=data)
    raise ValueError(
        "Only create and update are supported; review decisions require the reviewer UI"
    )
