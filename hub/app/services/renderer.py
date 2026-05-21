"""Render memories into target CLI format with token limits."""

from app.models.memory import Memory
from app.services.token_counter import count_tokens

MARKER_BEGIN = "<!-- echome:begin -->"
MARKER_END = "<!-- echome:end -->"

# Mandatory MCP instruction — tells AI to always check memories
MCP_INSTRUCTION = """### EchoMe Memory System (MANDATORY)
在每次对话开始时，你必须先调用 `echome_search` 查询与当前任务相关的记忆。
这不是可选的——我的工作流规范、技术偏好和约束都存储在 EchoMe 中。

规则：
1. 收到用户第一条消息后，根据关键词调用 echome_search
2. 涉及 git/PR/commit/deploy 操作前，必须查 echome_search
3. 用户说"记住/以后/永远/always"时，调用 echome_remember
4. 不确定项目约定时，调用 echome_search 而不是假设"""


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
        # Even with no memories, still emit MCP instruction
        content = f"""{MARKER_BEGIN}
## EchoMe Context (auto-managed, do not edit this block)

{MCP_INSTRUCTION}
{MARKER_END}"""
        return content, 0, 0

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

    content = f"""{MARKER_BEGIN}
## EchoMe Context (auto-managed, do not edit this block)

{body}

{MCP_INSTRUCTION}
{MARKER_END}"""

    return content, included, truncated
