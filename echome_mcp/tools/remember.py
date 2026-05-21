"""echome_remember - AI writes a new memory (pending user approval)."""

from echome_mcp.hub_client import MCPHubClient


async def echome_remember(
    title: str,
    content: str,
    type: str,
    tags: list[str],
    suggested_layer: str = "L2",
    project_id: str | None = None,
) -> str:
    """Write a new memory to the user's vault (requires user confirmation).

    Only call this when the user explicitly says to remember something,
    e.g. "remember this", "always do this", "from now on".

    Args:
        title: Short, descriptive title for the memory.
        content: Detailed content of the rule/knowledge/preference.
        type: Memory type (persona, workflow, tech, constraint, snippet,
              decision, knowledge, interaction, project).
        tags: List of relevant tags.
        suggested_layer: Suggested loading layer (L0/L1/L2, default L2).
        project_id: If project-specific, the project ID.

    Returns:
        Confirmation message.
    """
    client = MCPHubClient()

    scope = {"global": True, "projects": [], "exclude_projects": []}
    if project_id:
        scope = {"global": False, "projects": [project_id], "exclude_projects": []}

    data = {
        "title": title,
        "content": content,
        "type": type,
        "layer": suggested_layer,
        "priority": 5,
        "tags": tags,
        "status": "pending",  # Always pending - requires user approval
        "scope": scope,
        "source": "ai_suggested",
    }

    try:
        result = await client.create_memory(data)
        memory_id = result.get("id", "unknown")
        return (
            f"Memory saved (pending confirmation).\n\n"
            f"Title: {title}\n"
            f"Type: {type}\n"
            f"Status: pending (user must run `eme review` to approve)\n"
            f"ID: {memory_id}\n\n"
            f"The user will need to confirm this memory before it becomes active."
        )
    except Exception as e:
        return f"Error saving memory: {e}"
