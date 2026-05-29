"""echome_get_memories - Get multiple memories by UUID."""

from echome_mcp.hub_client import MCPHubClient


def _format_memory(mem: dict) -> str:
    title = mem.get("title", "Untitled")
    content = mem.get("content", "")
    mem_id = mem.get("id", "")
    mem_type = mem.get("type", "")
    layer = mem.get("layer", "")
    tags = ", ".join(mem.get("tags", []))
    priority = mem.get("priority", 0)

    return (
        f"## {title}\n\n"
        f"ID: {mem_id}\n"
        f"Type: {mem_type} | Layer: {layer} | Priority: {priority}\n"
        f"Tags: {tags}\n\n"
        f"{content}"
    )


async def echome_get_memories(memory_ids: list[str]) -> str:
    """Get full content for multiple memory UUIDs."""
    if not memory_ids:
        return "No memory IDs provided."

    client = MCPHubClient()
    output_parts: list[str] = []

    for memory_id in memory_ids:
        try:
            mem = await client.get_memory(memory_id)
        except Exception as e:
            output_parts.append(f"## {memory_id}\n\nError fetching memory: {e}")
            continue
        output_parts.append(_format_memory(mem))

    return "\n\n---\n\n".join(output_parts)
