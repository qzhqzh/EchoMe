"""echome_search_summary - Browse compact memory index entries."""

from echome_mcp.hub_client import MCPHubClient


def _summarize(content: str, max_chars: int = 160) -> str:
    """Return a compact one-line summary from memory content."""
    summary = " ".join(content.split())
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 3] + "..."


async def echome_search_summary(
    type: str | None = None,  # noqa: A002
    status: str = "active",
    project_id: str | None = None,
    query: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> str:
    """Browse memory index entries without loading full search results."""
    client = MCPHubClient()

    try:
        result = await client.browse_memories(
            memory_type=type,
            status=status,
            project_id=project_id,
            query=query,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        return f"Error browsing memories: {e}"

    items = result.get("items", [])
    total = result.get("total", len(items))
    if not items:
        return "No memories found for these filters."

    output_parts = [
        f"## Memory Search Summary ({len(items)} shown / {total} total)",
        "",
        "Pick the numbered entries that matter, then call `echome_get_memories(memory_ids=[...])` with their UUIDs for full content.",
        "",
    ]

    for index, item in enumerate(items, offset + 1):
        mem_id = str(item.get("id", ""))
        title = item.get("title", "Untitled")
        mem_type = item.get("type", "")
        layer = item.get("layer", "")
        priority = item.get("priority", 0)
        tags = ", ".join(item.get("tags", []))
        updated_at = item.get("updated_at", "")
        content = item.get("content", "")
        summary = _summarize(content) if content else ""

        output_parts.append(f"{index}. `{mem_id}` **{title}**")
        output_parts.append(
            f"   Type: {mem_type} | Layer: {layer} | P{priority} | Updated: {updated_at}"
        )
        if tags:
            output_parts.append(f"   Tags: {tags}")
        if summary:
            output_parts.append(f"   Summary: {summary}")

    next_offset = offset + len(items)
    if next_offset < total:
        output_parts.append("")
        output_parts.append(f"More results available: call again with `offset={next_offset}`.")

    return "\n".join(output_parts)


async def echome_browse_memories(
    type: str | None = None,  # noqa: A002
    status: str = "active",
    project_id: str | None = None,
    query: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> str:
    """Backward-compatible alias for echome_search_summary."""
    return await echome_search_summary(
        type=type,
        status=status,
        project_id=project_id,
        query=query,
        limit=limit,
        offset=offset,
    )
