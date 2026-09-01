"""echome_project - Project management tools."""

import json

import httpx

from echome_mcp.hub_client import MCPHubClient


def _reusable_project_candidate(
    discovery: dict[str, object],
) -> tuple[dict[str, object], float] | None:
    status = discovery.get("status")
    raw_candidates = discovery.get("candidates")
    candidates = (
        [
            candidate
            for candidate in raw_candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("project"), dict)
        ]
        if isinstance(raw_candidates, list)
        else []
    )
    if status == "resolved":
        resolution = discovery.get("resolution")
        canonical_id = (
            resolution.get("canonical_project_id") if isinstance(resolution, dict) else None
        )
        candidate = next(
            (item for item in candidates if item["project"].get("id") == canonical_id),
            candidates[0] if len(candidates) == 1 else None,
        )
    elif status == "needs_confirmation" and len(candidates) == 1:
        candidate = candidates[0]
    else:
        candidate = None
    if candidate is None:
        return None
    project = candidate["project"]
    if not isinstance(project.get("id"), str) or not str(project["id"]).strip():
        return None
    confidence = candidate.get("confidence", 1.0)
    return project, float(confidence) if isinstance(confidence, int | float) else 1.0


def _path_alias_value(pattern: str) -> str | None:
    wildcard_indexes = [pattern.find(marker) for marker in ("*", "?", "[")]
    wildcard_indexes = [index for index in wildcard_indexes if index >= 0]
    prefix = pattern[: min(wildcard_indexes, default=len(pattern))].rstrip("/\\")
    return prefix or None


def _project_alias_requests(
    *,
    candidate: dict[str, object],
    canonical_id: str,
    name: str,
    git_remote: str | None,
    path_patterns: list[str],
) -> list[dict[str, str]]:
    aliases: list[dict[str, str]] = []
    candidate_id = str(candidate.get("id") or "")
    candidate_name = str(candidate.get("name") or "")
    if canonical_id and canonical_id != candidate_id:
        aliases.append({"alias_type": "legacy_id", "alias_value": canonical_id})
    if name and name.casefold() != candidate_name.casefold():
        aliases.append({"alias_type": "name", "alias_value": name})
    if git_remote:
        aliases.append({"alias_type": "git_remote", "alias_value": git_remote})
    for pattern in path_patterns:
        path_alias = _path_alias_value(pattern)
        if path_alias:
            aliases.append({"alias_type": "path", "alias_value": path_alias})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for alias in aliases:
        key = (alias["alias_type"], alias["alias_value"])
        unique.setdefault(key, alias)
    return list(unique.values())[:10]


def _project_alias_error(exc: httpx.HTTPStatusError) -> str:
    try:
        response_payload = exc.response.json()
    except ValueError:
        response_payload = {}
    detail = response_payload.get("detail") if isinstance(response_payload, dict) else None
    if isinstance(detail, dict):
        code = str(detail.get("code") or "PROJECT_ALIAS_UPDATE_FAILED")
        message = str(detail.get("message") or exc)
        conflict_ids = detail.get("canonical_project_ids")
    else:
        code = "PROJECT_ALIAS_UPDATE_FAILED"
        message = str(detail or exc)
        conflict_ids = None
    error_details: dict[str, object] = {
        "code": code,
        "message": message,
        "retryable": False,
        "request_id": exc.response.headers.get("x-request-id", "hub-response"),
        "degraded": False,
        "suggested_action": "Retry echome_context with the returned canonical candidates.",
    }
    if isinstance(conflict_ids, list):
        error_details["canonical_project_ids"] = conflict_ids
    return json.dumps(
        {"schema_version": "echome.error.v1", "error": error_details},
        ensure_ascii=False,
        indent=2,
    )


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
        confirmed_new_project: 已弃用的兼容参数；新项目不再要求显式确认
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
        reusable_candidate = _reusable_project_candidate(discovery)
        if reusable_candidate is not None and not confirmed_distinct_project:
            candidate, confidence = reusable_candidate
            candidate_id = str(candidate.get("id") or "")
            aliases = _project_alias_requests(
                candidate=candidate,
                canonical_id=canonical_id,
                name=name,
                git_remote=git_remote,
                path_patterns=path_patterns,
            )
            if aliases:
                try:
                    await client.ensure_project_aliases(
                        canonical_project_id=candidate_id,
                        aliases=aliases,
                        confidence=confidence,
                    )
                except httpx.HTTPStatusError as exc:
                    return _project_alias_error(exc)
                except Exception as exc:
                    raise RuntimeError(f"自动写入项目 alias 失败: {exc}") from exc
            return (
                "已复用现有项目并自动确保身份 alias，无需创建重复项目。\n\n"
                f"- Canonical ID: {candidate_id}\n"
                f"- Alias 数量: {len(aliases)}"
            )
        if discovery_status != "not_found" and not confirmed_distinct_project:
            candidates = discovery.get("candidates") or []
            candidate_ids = [
                item.get("project", {}).get("id")
                for item in candidates
                if isinstance(item, dict) and isinstance(item.get("project"), dict)
            ]
            candidate_text = ", ".join(item for item in candidate_ids if item) or "未知"
            return (
                "未创建项目：存在多个或无法唯一选择的候选。"
                f"候选 canonical project: {candidate_text}。"
                "请先用候选 ID 重试 echome_context；确认候选均为其他项目后，"
                "可设置 confirmed_distinct_project=true 再创建。"
            )

    # 检查项目是否已存在
    try:
        existing = await client.get_project(canonical_id)
        if existing:
            return f"项目 '{canonical_id}' 已存在。无需重复创建。"
    except Exception as exc:
        raise RuntimeError(f"创建前项目检查失败: {exc}") from exc

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
            "retryable": code == "PROJECT_GIT_IDENTITY_PREVIEW_REQUIRED",
            "request_id": exc.response.headers.get("x-request-id", "hub-response"),
            "degraded": False,
            "suggested_action": (
                "Call this tool again with confirmed=false to obtain a current preview token."
                if code == "PROJECT_GIT_IDENTITY_PREVIEW_REQUIRED"
                else (
                    "Retry with the intended canonical project ID after resolving the conflict."
                    if exc.response.status_code == 409
                    else "Check the project ID and proposed Git identity."
                )
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
