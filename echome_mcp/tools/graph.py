"""Graph memory MCP tools for provenance and temporal reasoning."""

import json
from typing import Any

from echome_mcp.hub_client import MCPHubClient


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


async def echome_memory_neighbors(
    memory_id: str,
    depth: int = 1,
    include_inactive: bool = True,
    limit: int = 200,
) -> str:
    """Return a local memory graph around one memory as JSON."""
    client = MCPHubClient()
    try:
        result = await client.memory_neighbors(
            memory_id=memory_id,
            depth=depth,
            include_inactive=include_inactive,
            limit=limit,
        )
    except Exception as e:
        return f"Error fetching memory neighbors: {e}"

    return _json(result)


async def echome_memory_explain(
    memory_id: str,
    include_inactive: bool = True,
) -> str:
    """Explain one memory using graph provenance, successors, and temporal status."""
    client = MCPHubClient()
    try:
        result = await client.memory_explain(
            memory_id=memory_id,
            include_inactive=include_inactive,
        )
    except Exception as e:
        return f"Error explaining memory: {e}"

    memory = result.get("memory", {})
    assessment = result.get("temporal_assessment", {})
    incoming = result.get("incoming_edges", [])
    outgoing = result.get("outgoing_edges", [])
    related = result.get("related_memories", [])
    feedback = result.get("feedback_summary", {})

    summary = {
        "memory_id": memory.get("id"),
        "title": memory.get("title"),
        "classification": assessment.get("classification"),
        "confidence": assessment.get("confidence"),
        "signals": assessment.get("signals", []),
        "stable_signals": assessment.get("stable_signals", []),
        "incoming_edges": len(incoming),
        "outgoing_edges": len(outgoing),
        "related_memories": len(related),
        "feedback_summary": feedback,
        "usage_hint": (
            "Use this after search/get when you need provenance, supersession, "
            "neighbor context, or temporal reliability. It complements normal search."
        ),
    }

    return "## Memory Graph Explanation\n\n" + _json(summary) + "\n\n## Raw\n\n" + _json(result)


async def echome_temporal_candidates(
    project_id: str | None = None,
    include_inactive: bool = False,
    classifications: str | None = None,
    limit: int = 100,
) -> str:
    """List memories that may need temporal review without changing memory state."""
    client = MCPHubClient()
    try:
        result = await client.temporal_candidates(
            project_id=project_id,
            include_inactive=include_inactive,
            classifications=classifications,
            limit=limit,
        )
    except Exception as e:
        return f"Error fetching temporal candidates: {e}"

    return _json(result)
