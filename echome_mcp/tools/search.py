"""echome_search - Search user memories by keyword/semantic query."""

from echome_mcp.hub_client import MCPHubClient


async def echome_search(
    query: str,
    type: str | None = None,  # noqa: A002
    project_id: str | None = None,
    top_k: int = 5,
) -> str:
    """Search user memories and return formatted results.

    Args:
        query: Search keywords or natural language question.
        type: Optional filter by memory type.
        project_id: Optional filter by project.
        top_k: Number of results to return (default 5).

    Returns:
        Formatted search results as text.
    """
    client = MCPHubClient()

    try:
        result = await client.search(
            query=query,
            memory_type=type,
            project_id=project_id,
            top_k=top_k,
        )
    except Exception as e:
        return f"Error searching memories: {e}"

    results = result.get("results", [])
    if not results:
        return "No matching memories found."

    output_parts = [f"Found {len(results)} relevant memories:\n"]

    for i, item in enumerate(results, 1):
        score = item.get("score", 0)
        title = item.get("title", "Untitled")
        content = item.get("content", "")
        mem_type = item.get("type", "")
        tags = ", ".join(item.get("tags", []))

        output_parts.append(f"## {i}. {title} (score: {score:.2f})")
        output_parts.append(f"Type: {mem_type} | Tags: {tags}\n")
        output_parts.append(f"{content}\n")

    return "\n".join(output_parts)
