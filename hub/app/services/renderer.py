"""Render memories into target CLI format with token limits."""

from app.models.memory import Memory
from app.services.token_counter import count_tokens

MARKER_BEGIN = "<!-- echome:begin -->"
MARKER_END = "<!-- echome:end -->"


def render_memories(
    memories: list[Memory],
    target: str,
    max_tokens: int,
) -> tuple[str, int, int]:
    """Render memories into markdown format for a target CLI.

    Returns:
        (rendered_content, memories_included, memories_truncated)
    """
    if not memories:
        return "", 0, 0

    sections: list[str] = []
    current_tokens = 0
    included = 0
    truncated = 0

    # Group by type for cleaner output
    type_groups: dict[str, list[Memory]] = {}
    for mem in memories:
        type_groups.setdefault(mem.type, []).append(mem)

    type_headers = {
        "persona": "Identity & Style",
        "workflow": "Workflow Rules",
        "tech": "Technical Preferences",
        "constraint": "Constraints & Boundaries",
        "interaction": "Communication Preferences",
        "project": "Project Context",
        "snippet": "Snippets",
        "decision": "Decisions",
        "knowledge": "Knowledge",
    }

    for type_name, type_mems in type_groups.items():
        header = f"### {type_headers.get(type_name, type_name.title())}\n"
        header_tokens = count_tokens(header)

        if current_tokens + header_tokens > max_tokens:
            truncated += len(type_mems)
            continue

        section_parts = [header]
        current_tokens += header_tokens

        for mem in type_mems:
            entry = f"- **{mem.title}**: {mem.content}\n"
            entry_tokens = count_tokens(entry)

            if current_tokens + entry_tokens > max_tokens:
                truncated += 1
                continue

            section_parts.append(entry)
            current_tokens += entry_tokens
            included += 1

        if len(section_parts) > 1:  # Has content beyond header
            sections.append("".join(section_parts))

    # Wrap in markers
    body = "\n".join(sections)

    if target == "claude":
        content = f"""{MARKER_BEGIN}
## EchoMe Context (auto-managed, do not edit this block)

{body}

### How to get more context
When you need my past decisions, project background, or preferences,
call the MCP tool `echome_search` to retrieve relevant memories.
{MARKER_END}"""
    elif target == "codex":
        content = f"""{MARKER_BEGIN}
## EchoMe Context (auto-managed, do not edit this block)

{body}

### How to get more context
When you need my past decisions, project background, or preferences,
call the MCP tool `echome_search` to retrieve relevant memories.
{MARKER_END}"""
    else:
        content = f"""{MARKER_BEGIN}
{body}
{MARKER_END}"""

    return content, included, truncated
