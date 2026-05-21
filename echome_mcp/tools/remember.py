"""echome_remember - AI writes a new memory (pending user approval)."""

from echome_mcp.hub_client import MCPHubClient

# Valid types and common aliases that AI might use
VALID_TYPES = {
    "persona", "workflow", "tech", "constraint",
    "snippet", "decision", "knowledge", "interaction", "project",
}

# Mapping for common AI mistakes → correct type
TYPE_ALIASES = {
    "feedback": "interaction",
    "preference": "interaction",
    "style": "interaction",
    "rule": "workflow",
    "rules": "workflow",
    "process": "workflow",
    "convention": "workflow",
    "technology": "tech",
    "technical": "tech",
    "stack": "tech",
    "tool": "tech",
    "tools": "tech",
    "framework": "tech",
    "limit": "constraint",
    "boundary": "constraint",
    "forbidden": "constraint",
    "safety": "constraint",
    "code": "snippet",
    "template": "snippet",
    "context": "project",
    "background": "project",
    "info": "knowledge",
    "fact": "knowledge",
    "domain": "knowledge",
    "architecture": "decision",
    "choice": "decision",
}


def _normalize_type(raw_type: str) -> str:
    """Normalize a memory type, mapping aliases to valid types."""
    t = raw_type.lower().strip()
    if t in VALID_TYPES:
        return t
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    # Default fallback
    return "knowledge"


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
        type: Memory type. Valid: persona, workflow, tech, constraint,
              snippet, decision, knowledge, interaction, project.
        tags: List of relevant tags.
        suggested_layer: Suggested loading layer (L0/L1/L2, default L2).
        project_id: If project-specific, the project ID.

    Returns:
        Confirmation message.
    """
    client = MCPHubClient()

    # Normalize type to avoid 422 errors
    normalized_type = _normalize_type(type)

    scope = {"global": True, "projects": [], "exclude_projects": []}
    if project_id:
        scope = {"global": False, "projects": [project_id], "exclude_projects": []}

    data = {
        "title": title,
        "content": content,
        "type": normalized_type,
        "layer": suggested_layer if suggested_layer in ("L0", "L1", "L2") else "L2",
        "priority": 5,
        "tags": tags,
        "status": "pending",
        "scope": scope,
        "source": "ai_suggested",
    }

    try:
        result = await client.create_memory(data)
        memory_id = result.get("id", "unknown")

        type_note = ""
        if normalized_type != type.lower().strip():
            type_note = f" (normalized from '{type}' -> '{normalized_type}')"

        return (
            f"Memory saved (pending confirmation).\n\n"
            f"Title: {title}\n"
            f"Type: {normalized_type}{type_note}\n"
            f"Status: pending (user must run `echome review` to approve)\n"
            f"ID: {memory_id}\n\n"
            f"The user will need to confirm this memory before it becomes active."
        )
    except Exception as e:
        return f"Error saving memory: {e}"
