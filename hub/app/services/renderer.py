"""Render memories into target CLI format with token limits.

Memories are rendered in priority order by type, ensuring the most impactful
categories (persona, constraints) are never truncated before less critical ones.
"""

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
3. 用户说"记住/以后/永远/always"时，必须调用 MCP tool `echome_remember`（不要用 bash 命令 `echome add`）
4. 不确定项目约定时，调用 echome_search 而不是假设
5. 写入记忆时 type 只能是：identity, guardrail, reasoning, method, stack, style, decision, context, template, project
6. **完成任务时写入记忆**：完成一个有价值的任务后，主动判断是否需要用 `echome_remember` 写入记忆。判断标准：
   - 发现了可复用的模式、踩坑经验、最佳实践
   - 用户纠正了你的做法（存为 style 类型）
   - 做了技术决策（存为 decision 类型）
   - 学到了项目特有的知识（存为 context 或 project 类型）
   不要写：密码/密钥/隐私、一次性临时信息、会快速过时的内容"""

# Type rendering priority (lower number = higher priority = rendered first)
TYPE_PRIORITY: dict[str, int] = {
    "identity": 1,
    "guardrail": 2,
    "reasoning": 3,
    "method": 4,
    "stack": 5,
    "style": 6,
    "decision": 7,
    "context": 8,
    "template": 9,
    "project": 10,
}

# Human-readable section headers with emoji markers for visual scanning
TYPE_HEADERS: dict[str, str] = {
    "identity": "🧠 Identity & Style",
    "guardrail": "🚫 Constraints (RED LINES)",
    "reasoning": "💡 Thinking Framework",
    "method": "⚡ Workflow & Methods",
    "stack": "🔧 Technical Preferences",
    "style": "💬 Communication Style",
    "decision": "📋 Decisions",
    "context": "📚 Knowledge & Context",
    "template": "📝 Templates & Snippets",
    "project": "📁 Project Context",
}


def render_memories(
    memories: list[Memory],
    target: str,
    max_tokens: int,
) -> tuple[str, int, int]:
    """Render memories into markdown format for a target CLI.

    Memories are grouped by type and rendered in priority order:
    persona > constraint > workflow > tech > interaction > decision > knowledge > snippet > project

    Within each type group, memories are ordered by priority (desc).

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

    # Group by type
    type_groups: dict[str, list[Memory]] = {}
    for mem in memories:
        type_groups.setdefault(mem.type, []).append(mem)

    # Sort each group by priority (desc) within type
    for type_mems in type_groups.values():
        type_mems.sort(key=lambda m: m.priority, reverse=True)

    # Render in type priority order
    sorted_types = sorted(
        type_groups.keys(),
        key=lambda t: TYPE_PRIORITY.get(t, 99),
    )

    for type_name in sorted_types:
        type_mems = type_groups[type_name]
        header = f"### {TYPE_HEADERS.get(type_name, type_name.title())}\n"
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
