"""echome_remember - AI writes a new memory in ai_review state."""

from echome_mcp.hub_client import MCPHubClient

# Valid types (must match the database CHECK constraint)
VALID_TYPES = {
    "identity", "guardrail", "reasoning", "method", "stack",
    "style", "decision", "context", "template", "project",
}

# Mapping for common AI mistakes → correct valid type
TYPE_ALIASES = {
    "feedback": "style",
    "preference": "style",
    "interaction": "style",
    "rule": "method",
    "rules": "method",
    "process": "method",
    "convention": "method",
    "workflow": "method",
    "technology": "stack",
    "technical": "stack",
    "tech": "stack",
    "tool": "stack",
    "tools": "stack",
    "framework": "stack",
    "limit": "guardrail",
    "boundary": "guardrail",
    "forbidden": "guardrail",
    "constraint": "guardrail",
    "red_line": "guardrail",
    "safety": "guardrail",
    "code": "template",
    "snippet": "template",
    "background": "project",
    "info": "context",
    "fact": "context",
    "domain": "context",
    "knowledge": "context",
    "architecture": "decision",
    "choice": "decision",
    "persona": "identity",
    "character": "identity",
    "thinking": "reasoning",
}


def _normalize_type(raw_type: str) -> str:
    """Normalize a memory type, mapping aliases to valid types."""
    t = raw_type.lower().strip()
    if t in VALID_TYPES:
        return t
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    # Default fallback to a valid type
    return "context"


async def echome_remember(
    title: str,
    content: str,
    type: str,  # noqa: A002
    tags: list[str],
    suggested_layer: str = "L2",
    project_id: str | None = None,
) -> str:
    """Write a proposed memory to the user's vault in ai_review state.

    Agents may call this proactively when they observe durable user preferences,
    project decisions, workflow conventions, repeated corrections, or reusable
    context that is likely to help future sessions. Do not write secrets,
    one-off temporary facts, or uncertain guesses. Writes are immediately available to future AI queries as ai_review,
    and the user can later archive or promote them with `echome review`.

    Args:
        title: Short, descriptive title for the memory.
        content: Detailed content of the rule/knowledge/preference.
        type: Memory type. Valid: identity, guardrail, reasoning, method, stack,
              style, decision, context, template, project.
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
        "status": "ai_review",
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
            f"Memory saved (ai_review).\n\n"
            f"Title: {title}\n"
            f"Type: {normalized_type}{type_note}\n"
            f"Status: ai_review (available to AI; user may run `echome review` to promote/archive)\n"
            f"ID: {memory_id}\n\n"
            f"This memory is available to AI search now; the user can archive or promote it later."
        )
    except Exception as e:
        return f"Error saving memory: {e}"
