"""echome_get_project_context - Get full context for a project."""

from echome_mcp.hub_client import MCPHubClient


async def echome_get_project_context(project_id: str | None = None) -> str:
    """Get the full context for a project including all scoped memories.

    Args:
        project_id: Project ID (e.g. 'qzhqzh/EchoMe').
                    If not provided, returns global context only.

    Returns:
        Formatted project context with all relevant memories.
    """
    client = MCPHubClient()

    if not project_id:
        return "No project_id provided. Use echome_search to find specific information."

    try:
        result = await client.get_project_memories(project_id)
    except Exception as e:
        return f"Error fetching project context: {e}"

    items = result.get("items", [])
    if not items:
        return f"No memories found for project '{project_id}'."

    output_parts = [f"# Project Context: {project_id}\n"]

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for item in items:
        mem_type = item.get("type", "other")
        by_type.setdefault(mem_type, []).append(item)

    type_headers = {
        "persona": "Identity & Style",
        "workflow": "Workflow Rules",
        "tech": "Technical Preferences",
        "constraint": "Constraints",
        "project": "Project Details",
        "decision": "Past Decisions",
        "knowledge": "Domain Knowledge",
    }

    for mem_type, memories in by_type.items():
        header = type_headers.get(mem_type, mem_type.title())
        output_parts.append(f"\n## {header}\n")
        for mem in memories:
            title = mem.get("title", "")
            content = mem.get("content", "")
            output_parts.append(f"### {title}\n{content}\n")

    return "\n".join(output_parts)
