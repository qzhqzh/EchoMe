"""Render memories into target CLI format with token limits.

Memories are rendered in priority order by type, ensuring the most impactful
categories (persona, constraints) are never truncated before less critical ones.
"""

from app.models.memory import Memory
from app.services.token_counter import count_tokens

MARKER_BEGIN = "<!-- echome:begin -->"
MARKER_END = "<!-- echome:end -->"

# On-demand memory protocol shared by supported clients.
MCP_INSTRUCTION = """### EchoMe 按需上下文
- 仅当历史偏好、项目决策或不确定约定影响当前任务时调用 `echome_context`，传任务和已知项目线索；当前上下文足够时不重复查询或例行复述。
- 首次使用或不确定工具时读 `echome_capabilities`。未知项目、没有命中或工具不可用时按当前证据继续，不静默创建项目。
- 记忆影响决策且来源、时效或冲突未解决时，用 `echome_memory_explain` 核对；当前用户指令和仓库事实优先。
- 用户明确要求记住持久信息时用 `echome_remember`。主动写入仅限可复用知识；用简短 Markdown，类型限 identity、guardrail、reasoning、method、stack、style、decision、context、template、project。通用记忆不传 project；项目记忆用已存在的 canonical project、suggested_layer="L1"、ai_review。
- 有明确纠正或有效性证据时记录 feedback；有有效 completion_contract 且结果可判断时提交一次 `echome_context_outcome`，保留 run id 和幂等键，不给缓存降级结果报 outcome。
- 记忆流程不阻断已授权的本地工作。实现、运行适当检查、检查结果、修复失败并重新验证后才算完成；不要因指南中的例行确认提前停工。"""

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
