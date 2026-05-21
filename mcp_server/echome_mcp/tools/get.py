"""echome_get - Get a single memory by ID."""

from echome_mcp.hub_client import MCPHubClient


async def echome_get(memory_id: str) -> str:
    """Get a single memory's full content by ID.

    Args:
        memory_id: UUID of the memory.

    Returns:
        Formatted memory content.
    """
    client = MCPHubClient()

    try:
        mem = await client.get_memory(memory_id)
    except Exception as e:
        return f"Error fetching memory: {e}"

    title = mem.get("title", "Untitled")
    content = mem.get("content", "")
    mem_type = mem.get("type", "")
    layer = mem.get("layer", "")
    tags = ", ".join(mem.get("tags", []))
    priority = mem.get("priority", 0)

    return (
        f"# {title}\n\n"
        f"Type: {mem_type} | Layer: {layer} | Priority: {priority}\n"
        f"Tags: {tags}\n\n"
        f"{content}"
    )
