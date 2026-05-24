"""echome_project - Project management tools."""

from echome_mcp.hub_client import MCPHubClient


async def echome_list_projects() -> str:
    """List all projects for the current user.

    Returns:
        Formatted list of projects with ID and name.
    """
    client = MCPHubClient()

    try:
        projects = await client.list_projects()
    except Exception as e:
        return f"获取项目列表失败: {e}"

    if not projects:
        return "当前没有项目。可以使用 echome_create_project 创建新项目。"

    output_parts = [f"共有 {len(projects)} 个项目:\n"]
    for proj in projects:
        id_ = proj.get("id", "")
        name = proj.get("name", "")
        description = proj.get("description", "")
        git_remote = proj.get("git_remote", "")

        output_parts.append(f"- **{name}** (ID: `{id_}`)")
        if description:
            output_parts.append(f"  描述: {description}")
        if git_remote:
            output_parts.append(f"  Git: {git_remote}")

    return "\n".join(output_parts)


async def echome_create_project(
    name: str,
    description: str | None = None,
    git_remote: str | None = None,
) -> str:
    """Create a new project.

    Args:
        name: 项目名称（作为项目唯一标识和显示名称）
        description: 项目描述（可选）
        git_remote: Git 远程仓库地址（可选）

    Returns:
        Success message or error description.
    """
    client = MCPHubClient()

    # name 同时作为 id 和显示名称
    project_id = name

    # 检查项目是否已存在
    try:
        existing = await client.get_project(project_id)
        if existing:
            return f"项目 '{project_id}' 已存在。无需重复创建。"
    except Exception:
        pass  # 继续创建

    # 创建项目
    try:
        result = await client.create_project(
            id=project_id,
            name=name,
            description=description,
            git_remote=git_remote,
        )
    except Exception as e:
        error_msg = str(e)
        if "409" in error_msg or "already exists" in error_msg.lower():
            return f"项目 '{project_id}' 已存在，无需重复创建。"
        return f"创建项目失败: {e}"

    return (
        f"项目创建成功！\n\n"
        f"- 名称: {result.get('name')}\n"
        f"- 描述: {result.get('description') or '无'}\n"
        f"- Git: {result.get('git_remote') or '无'}\n\n"
        f"现在可以使用 echome_remember 创建项目记忆，project_id 使用 '{result.get('name')}'。"
    )
