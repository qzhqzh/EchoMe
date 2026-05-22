"""echome_list_by_type - List memories by type."""

from echome_mcp.hub_client import MCPHubClient


async def echome_list_by_type(type: str, status: str = "active") -> str:
    """List all memories of a given type.

    Args:
        type: Memory type (identity, guardrail, reasoning, method, stack,
              style, decision, context, template, project).
        status: Filter by status (default: active).

    Returns:
        Formatted list of memory titles.
    """
    client = MCPHubClient()

    try:
        result = await client.list_by_type(type=type, status=status)
    except Exception as e:
        return f"Error listing memories: {e}"

    items = result.get("items", [])
    if not items:
        return f"No {status} memories of type '{type}' found."

    output_parts = [f"## {type.title()} Memories ({len(items)} total)\n"]

    for item in items:
        title = item.get("title", "Untitled")
        mem_id = str(item.get("id", ""))[:8]
        priority = item.get("priority", 0)
        tags = ", ".join(item.get("tags", []))
        output_parts.append(f"- [{mem_id}] **{title}** (P{priority}) {tags}")

    return "\n".join(output_parts)
