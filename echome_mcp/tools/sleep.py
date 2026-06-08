"""Memory Sleep MCP tools."""

import json
from typing import Any

from echome_mcp.hub_client import MCPHubClient


async def echome_sleep_candidates(
    project_id: str | None = None,
    session_id: str | None = None,
    scope: str = "project",
    status: list[str] | None = None,
    page_size: int = 100,
    cursor: int | None = None,
    include_protected: bool = True,
) -> str:
    """Fetch memory sleep candidates as JSON."""
    client = MCPHubClient()
    payload: dict[str, Any] = {
        "project_id": project_id,
        "session_id": session_id,
        "scope": scope,
        "page_size": page_size,
        "cursor": cursor,
        "include_protected": include_protected,
    }
    if status:
        payload["status"] = status

    try:
        result = await client.sleep_candidates(payload)
    except Exception as e:
        return f"Error fetching sleep candidates: {e}"

    return json.dumps(result, ensure_ascii=False, indent=2)


async def echome_sleep_submit_proposal(
    session_id: str,
    json_proposal: dict[str, Any],
    text_proposal: str | None = None,
) -> str:
    """Submit a memory sleep proposal."""
    client = MCPHubClient()
    try:
        result = await client.sleep_submit_proposal(
            session_id,
            {
                "text_proposal": text_proposal,
                "json_proposal": json_proposal,
            },
        )
    except Exception as e:
        return f"Error submitting sleep proposal: {e}"

    return json.dumps(result, ensure_ascii=False, indent=2)


async def echome_sleep_apply(session_id: str) -> str:
    """Apply an approved memory sleep proposal."""
    client = MCPHubClient()
    try:
        result = await client.sleep_apply(session_id, approved=True)
    except Exception as e:
        return f"Error applying sleep proposal: {e}"

    return json.dumps(result, ensure_ascii=False, indent=2)
