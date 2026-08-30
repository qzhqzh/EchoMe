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
EchoMe 存储了我的个人习惯、开发规范、技术偏好和项目约定。你必须在需要这些上下文时主动查询，但不要在每一轮对话都机械重复查询。

规则：
1. **能力发现**：如果是首次使用 EchoMe MCP，或不确定该调用哪个工具，先调用 `echome_capabilities` 读取工具分组和标准工作流。Codex、Claude、Cursor 等客户端都按这个 MCP 工作流处理。
2. **会话启动自检**：收到用户第一条任务消息后，调用 `echome_context`，传入当前任务；项目任务同时传 project hint 和已知 changed paths。它会自动选择 personal、project、impact 或 temporal 路径。
3. **首轮规范确认**：如果 context 返回了相关规范，用 1-3 句简短复述本次会遵守的关键规范，再开始执行任务。
4. **后续按需触发**：同一会话不要每轮重复查询。只有当用户提到偏好、规范、历史决策或项目约定，任务跨模块或高风险，出现不确定约定，或用户说“按老规矩/继续/记住/以后/永远/always”时，再调用 `echome_context`。
5. **没有命中就停止**：如果 context 没有相关记忆或明确返回 unknowns，不要为了凑结果扩大搜索；说明未找到相关记忆并以当前仓库事实继续。
6. **图解释与可靠性**：当某条记忆影响项目决策、部署、版本、历史方案或可能过时时，调用 `echome_memory_explain` 检查来源、替代关系、相邻记忆、temporal assessment 和 feedback summary。
7. **完成闭环**：`echome_context` 返回 `completion_contract` 时，保留其中的 run id 和幂等键；任务结束后调用一次 `echome_context_outcome`。有测试、提交、部署或用户纠正等证据时记录实际结果；无法判断上下文是否有效时记录 `no_signal`。不要为了评分打断用户，也不要给缓存降级结果回报 outcome。
8. 用户说"记住/以后/永远/always"时，必须调用 MCP tool `echome_remember`。
9. 写入记忆时 type 只能是：identity, guardrail, reasoning, method, stack, style, decision, context, template, project。写入前判断记忆范围：通用型不传 project；项目相关必须指定已存在的 canonical project，`suggested_layer="L1"`，状态默认为 ai_review。不要猜测或静默创建项目。
10. **记忆格式规范**：写入记忆时使用 Markdown 格式，内容必须结构化：
   - 核心规则/要点放在开头，用 `**bold**` 标记关键词
   - 多段落内容用 `##` 分节（如：核心规则、Why、How to apply）
   - 列表用 `-` 或 `1.`，不要写成一大段纯文本
11. **完成任务时写入记忆**：完成一个有价值的任务后，主动判断是否需要用 MCP tool `echome_remember` 写入记忆。判断标准：
   - 发现了可复用的模式、踩坑经验、最佳实践
   - 用户纠正了你的做法（存为 style 类型）
   - 做了技术决策（存为 decision 类型）
   - 学到了项目特有的知识（存为 context 或 project 类型）
   不要写：临时状态、一次性信息、会快速过时的内容"""

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
