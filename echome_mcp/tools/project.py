"""echome_project - Project management tools."""

import json

import httpx

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
        raise RuntimeError(f"获取项目列表失败: {e}") from e

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
    project_id: str | None = None,
    description: str | None = None,
    git_remote: str | None = None,
    kind: str = "repository",
    path_patterns: list[str] | None = None,
    confirmed_new_project: bool = False,
    confirmed_distinct_project: bool = False,
) -> str:
    """Create a new project.

    Args:
        name: 项目显示名称
        project_id: canonical project ID（默认使用 name）
        description: 项目描述（可选）
        git_remote: Git 远程仓库地址（可选）
        kind: repository 或 workspace
        path_patterns: 可识别该项目的路径模式
        confirmed_new_project: 用户明确确认这是新项目后才允许创建
        confirmed_distinct_project: 用户确认候选均为其他项目后允许继续创建

    Returns:
        Success message or error description.
    """
    client = MCPHubClient()

    canonical_id = project_id or name
    path_patterns = path_patterns or []

    discovery_hints = list(
        dict.fromkeys(hint for hint in [canonical_id, name, git_remote, *path_patterns] if hint)
    )
    try:
        discovery = await client.discover_projects(discovery_hints)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise RuntimeError(f"创建前项目发现失败: {exc}") from exc
    else:
        discovery_status = discovery.get("status")
        if discovery_status == "resolved" or (
            discovery_status != "not_found" and not confirmed_distinct_project
        ):
            candidates = discovery.get("candidates") or []
            candidate_ids = [
                item.get("project", {}).get("id")
                for item in candidates
                if isinstance(item, dict) and isinstance(item.get("project"), dict)
            ]
            candidate_text = ", ".join(item for item in candidate_ids if item) or "未知"
            return (
                "未创建项目：现有项目可能已覆盖该身份。"
                f"候选 canonical project: {candidate_text}。"
                "请先用候选 ID 重试 echome_context；用户确认候选均为其他项目后，"
                "可设置 confirmed_distinct_project=true 再创建。"
            )

    # 检查项目是否已存在
    try:
        existing = await client.get_project(canonical_id)
        if existing:
            return f"项目 '{canonical_id}' 已存在。无需重复创建。"
    except Exception as exc:
        raise RuntimeError(f"创建前项目检查失败: {exc}") from exc

    if not confirmed_new_project:
        return (
            "未创建项目：需要用户明确确认这是一个新项目。"
            "确认后请设置 confirmed_new_project=true；该确认不会绕过候选冲突检查。"
        )

    # 创建项目
    try:
        result = await client.create_project(
            id=canonical_id,
            name=name,
            description=description,
            git_remote=git_remote,
            kind=kind,
            path_patterns=path_patterns,
        )
    except Exception as e:
        error_msg = str(e)
        if "409" in error_msg or "already exists" in error_msg.lower():
            return f"项目 '{canonical_id}' 已存在，无需重复创建。"
        raise RuntimeError(f"创建项目失败: {e}") from e

    return (
        f"项目创建成功！\n\n"
        f"- ID: {result.get('id')}\n"
        f"- 名称: {result.get('name')}\n"
        f"- 类型: {result.get('kind')}\n"
        f"- 描述: {result.get('description') or '无'}\n"
        f"- Git: {result.get('git_remote') or '无'}\n\n"
        f"现在可以使用 echome_remember 创建项目记忆，project_id 使用 '{result.get('id')}'。"
    )


async def echome_update_project_git_identity(
    project_id: str,
    git_remote: str | None = None,
    git_remote_aliases: list[str] | None = None,
    confirmed: bool = False,
    confirmation_token: str | None = None,
) -> str:
    """Preview or apply a safe Git remote/alias update for an existing project."""
    client = MCPHubClient()
    try:
        result = await client.update_project_git_identity(
            project_id=project_id,
            git_remote=git_remote,
            git_remote_aliases=git_remote_aliases,
            confirmed=confirmed,
            confirmation_token=confirmation_token,
        )
    except httpx.HTTPStatusError as exc:
        try:
            response_payload = exc.response.json()
        except ValueError:
            response_payload = {}
        detail = response_payload.get("detail") if isinstance(response_payload, dict) else None
        if isinstance(detail, dict):
            code = str(detail.get("code") or "PROJECT_GIT_IDENTITY_UPDATE_FAILED")
            message = str(detail.get("message") or exc)
            conflict_ids = detail.get("canonical_project_ids")
        else:
            code = {
                404: "PROJECT_NOT_FOUND",
                409: "PROJECT_GIT_IDENTITY_CONFLICT",
                422: "INVALID_PROJECT_GIT_IDENTITY",
            }.get(exc.response.status_code, "PROJECT_GIT_IDENTITY_UPDATE_FAILED")
            message = str(detail or exc)
            conflict_ids = None
        error_details: dict[str, object] = {
            "code": code,
            "message": message,
            "retryable": False,
            "request_id": exc.response.headers.get("x-request-id", "hub-response"),
            "degraded": False,
            "suggested_action": (
                "Retry with the intended canonical project ID after resolving the conflict."
                if exc.response.status_code == 409
                else "Check the project ID and proposed Git identity."
            ),
        }
        if isinstance(conflict_ids, list):
            error_details["canonical_project_ids"] = conflict_ids
        error = {
            "schema_version": "echome.error.v1",
            "error": error_details,
        }
        return json.dumps(error, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise RuntimeError(f"更新项目 Git identity 失败: {exc}") from exc
    return json.dumps(result, ensure_ascii=False, indent=2)
