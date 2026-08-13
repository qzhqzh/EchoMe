"""Resolve project hints without rewriting historical project data."""

from __future__ import annotations

import fnmatch
import posixpath
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Project
from app.models.project_knowledge import ProjectAlias

ALIAS_TYPES = {"legacy_id", "name", "git_remote", "path", "client_hint"}
HISTORY_SCOPE_ALIAS_TYPES = {"legacy_id", "name", "client_hint"}


@dataclass(frozen=True)
class ProjectResolution:
    """A canonical project plus evidence explaining how it was selected."""

    project: Project
    matched_by: str
    confidence: float
    alias_id: str | None = None

    def payload(self, hint: str) -> dict[str, object]:
        return {
            "hint": hint,
            "canonical_project_id": self.project.id,
            "matched_by": self.matched_by,
            "confidence": self.confidence,
            "alias_id": self.alias_id,
        }


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def _normalize_git_remote(value: str) -> str:
    remote = _normalized_text(value)
    scp_match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", remote)
    if scp_match and "://" not in remote:
        host, path = scp_match.groups()
    else:
        parsed = urlsplit(remote if "://" in remote else f"https://{remote}")
        host = parsed.hostname or ""
        path = unquote(parsed.path)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host.casefold()}/{path.casefold()}".rstrip("/")


def normalize_project_hint(value: str, alias_type: str) -> str:
    """Normalize one alias type deterministically on both write and lookup."""
    if alias_type not in ALIAS_TYPES:
        raise ValueError(f"Unsupported project alias type: {alias_type}")
    if alias_type == "git_remote":
        normalized = _normalize_git_remote(value)
    elif alias_type == "path":
        text = _normalized_text(value).replace("\\", "/")
        normalized = posixpath.normpath(text)
    else:
        normalized = _normalized_text(value).casefold()
    if not normalized or normalized == ".":
        raise ValueError("Project alias value cannot be empty")
    return normalized


def infer_alias_types(hint: str) -> list[str]:
    """Return bounded lookup strategies for an untyped client hint."""
    value = hint.strip()
    if "://" in value or value.startswith("git@") or value.endswith(".git"):
        return ["git_remote", "client_hint"]
    if value.startswith(("/", "./", "../", "~", "\\")) or re.match(
        r"^[A-Za-z]:[\\/]", value
    ):
        return ["path", "client_hint"]
    return ["legacy_id", "name", "client_hint"]


async def _all_user_projects(session: AsyncSession, user_id: str) -> list[Project]:
    result = await session.execute(select(Project).where(Project.user_id == user_id))
    return list(result.scalars().all())


async def resolve_project(
    session: AsyncSession,
    user_id: str,
    hint: str,
    alias_type: str | None = None,
) -> ProjectResolution:
    """Resolve a hint to one project, refusing ambiguous or cross-user matches."""
    clean_hint = hint.strip()
    if not clean_hint:
        raise HTTPException(status_code=422, detail="Project hint cannot be empty")

    direct = await session.scalar(
        select(Project).where(Project.id == clean_hint, Project.user_id == user_id)
    )
    if direct is not None:
        return ProjectResolution(direct, "project_id", 1.0)

    lookup_types = [alias_type] if alias_type else infer_alias_types(clean_hint)
    try:
        normalized = {
            item_type: normalize_project_hint(clean_hint, item_type)
            for item_type in lookup_types
            if item_type is not None
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    alias_predicates = [
        (ProjectAlias.alias_type == item_type)
        & (ProjectAlias.normalized_value == value)
        for item_type, value in normalized.items()
    ]
    aliases: list[ProjectAlias] = []
    if alias_predicates:
        alias_result = await session.execute(
            select(ProjectAlias).where(
                ProjectAlias.user_id == user_id,
                ProjectAlias.status == "active",
                or_(*alias_predicates),
            )
        )
        aliases = list(alias_result.scalars().all())
    canonical_ids = {item.canonical_project_id for item in aliases}
    if len(canonical_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AMBIGUOUS_PROJECT_HINT",
                "message": "Project hint matches more than one canonical project",
                "candidates": sorted(canonical_ids),
            },
        )
    if aliases:
        alias = max(aliases, key=lambda item: item.confidence)
        project = await session.scalar(
            select(Project).where(
                Project.id == alias.canonical_project_id,
                Project.user_id == user_id,
            )
        )
        if project is not None:
            return ProjectResolution(
                project,
                f"alias:{alias.alias_type}",
                alias.confidence,
                str(alias.id),
            )

    projects = await _all_user_projects(session, user_id)
    fallback: list[tuple[Project, str, float]] = []
    for project in projects:
        if (
            "git_remote" in normalized
            and project.git_remote
            and normalize_project_hint(project.git_remote, "git_remote")
            == normalized["git_remote"]
        ):
            fallback.append((project, "project_git_remote", 0.95))
        if "name" in normalized and normalize_project_hint(
            project.name, "name"
        ) == normalized["name"]:
            fallback.append((project, "project_name", 0.75))
        if "path" in normalized:
            path = normalized["path"]
            patterns: list[str] = []
            for pattern in project.path_patterns or []:
                try:
                    patterns.append(normalize_project_hint(pattern, "path"))
                except ValueError:
                    continue
            if any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
                fallback.append((project, "project_path_pattern", 0.85))
    fallback_ids = {item[0].id for item in fallback}
    if len(fallback_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AMBIGUOUS_PROJECT_HINT",
                "message": "Project hint matches more than one configured project",
                "candidates": sorted(fallback_ids),
            },
        )
    if fallback:
        project, matched_by, confidence = max(fallback, key=lambda item: item[2])
        return ProjectResolution(project, matched_by, confidence)
    raise HTTPException(status_code=404, detail="Project not found")


async def project_scope_ids(
    session: AsyncSession,
    user_id: str,
    canonical_project_id: str,
) -> list[str]:
    """Expand active historical ID-like aliases for read-only queries."""
    result = await session.execute(
        select(ProjectAlias).where(
            ProjectAlias.user_id == user_id,
            ProjectAlias.canonical_project_id == canonical_project_id,
            ProjectAlias.status == "active",
            ProjectAlias.alias_type.in_(HISTORY_SCOPE_ALIAS_TYPES),
        )
    )
    values = {canonical_project_id}
    values.update(item.alias_value for item in result.scalars().all())
    return sorted(values)


async def canonicalize_project_scopes(
    session: AsyncSession,
    user_id: str,
    project_ids: list[str],
) -> list[str]:
    """Resolve known aliases on writes while preserving unknown legacy scopes."""
    canonical: list[str] = []
    for project_id in project_ids:
        try:
            resolved = await resolve_project(session, user_id, project_id)
            value = resolved.project.id
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            value = project_id
        if value not in canonical:
            canonical.append(value)
    return canonical
