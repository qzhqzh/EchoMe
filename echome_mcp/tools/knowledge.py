"""Explicit, bounded knowledge operations. Consequential reviewer actions are not tools."""

import json
from typing import Any
from uuid import UUID

import httpx

from echome_mcp.hub_client import MCPHubClient


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
    action: str, record_id: str | None = None, data: dict[str, Any] | None = None
) -> str:
    """Read contracts, exact structured queries, discovery, history or a context bundle."""
    data = data or {}
    if action == "schema":
        return await _request("GET", "/schema")
    if action == "list":
        return await _request("GET", "/records", params=data)
    if action == "query":
        return await _request("POST", "/query", data=data)
    if action not in ("get", "history", "backlinks", "context"):
        raise ValueError("Unknown knowledge read action")
    if not record_id:
        raise ValueError("record_id is required")
    path = "/records/" + str(UUID(record_id))
    if action != "get":
        path += "/" + action
    return await _request("GET", path, params=data)


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
