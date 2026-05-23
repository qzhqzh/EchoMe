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
    project: str | None = None,
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
        project: Only for 'project' type - the project name.

    Returns:
        Confirmation message.
    """
    client = MCPHubClient()

    # Normalize type to avoid 422 errors
    normalized_type = _normalize_type(type)

    # 非 project 类型不允许关联项目
    if normalized_type != "project" and project:
        return (
            f"'{normalized_type}' 类型记忆不需要关联项目。\n"
            f"只有 'project' 类型记忆才需要提供 project 参数。\n"
            f"请移除 project 参数，或将类型改为 'project'。"
        )

    # 当 type 为 project 时，检查项目是否存在
    if normalized_type == "project":
        if not project:
            return (
                "创建 project 类型记忆需要提供项目名称(project)。\n\n"
                "请先调用 echome_create_project 创建项目，只需提供：\n"
                "- name: 项目名称（作为唯一标识）\n"
                "- description: 项目描述（可选）\n"
                "- git_remote: Git 仓库地址（可选）\n\n"
                "创建项目后，再调用 echome_remember 创建项目记忆。"
            )

        # 检查项目是否存在（project 就是项目名称，也是 id）
        try:
            existing_project = await client.get_project(project)
            if not existing_project:
                return (
                    f"项目 '{project}' 不存在。\n\n"
                    "请先调用 echome_create_project 创建项目，只需提供：\n"
                    "- name: 项目名称\n"
                    "- description: 项目描述（可选）\n"
                    "- git_remote: Git 仓库地址（可选）\n\n"
                    "创建项目后，再调用 echome_remember 创建项目记忆。"
                )
        except Exception as e:
            return f"检查项目 '{project}' 时出错: {e}"

    # 非 project 类型：全局 scope
    # project 类型：关联到指定项目
    if normalized_type == "project":
        scope = {"global": False, "projects": [project], "exclude_projects": []}
    else:
        scope = {"global": True, "projects": [], "exclude_projects": []}

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
