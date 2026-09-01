"""Resolve project hints without rewriting historical project data."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
import re
import secrets
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Project
from app.models.project_knowledge import ProjectAlias, ProjectRelation

ALIAS_TYPES = {"legacy_id", "name", "git_remote", "path", "client_hint"}
HISTORY_SCOPE_ALIAS_TYPES = {"legacy_id", "name", "client_hint"}
ENVIRONMENT_SUFFIXES = {
    "dev",
    "development",
    "local",
    "prod",
    "production",
    "qa",
    "stage",
    "staging",
    "test",
    "testing",
    "uat",
}
WORKSPACE_GENERIC_TOKENS = {"ecosystem", "suite", "workspace"}
AUTO_RESOLVE_CONFIDENCE = 0.86
AUTO_RESOLVE_MARGIN = 0.08


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


@dataclass(frozen=True)
class ProjectContextScope:
    """Canonical projects and historical IDs eligible for one context request."""

    exact_project_id: str
    canonical_project_ids: tuple[str, ...]
    memory_scope_ids: tuple[str, ...]
    inherited_project_ids: tuple[str, ...]
    selected_child_project_ids: tuple[str, ...]
    scope_ids_by_project: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ProjectCandidate:
    """A non-binding project suggestion with deterministic matching evidence."""

    project: Project
    confidence: float
    matched_by: tuple[str, ...]
    matched_hints: tuple[str, ...]
    workspace_parents: tuple[str, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "project": {
                "id": self.project.id,
                "name": self.project.name,
                "kind": self.project.kind,
            },
            "confidence": self.confidence,
            "matched_by": list(self.matched_by),
            "matched_hints": list(self.matched_hints),
            "workspace_parents": list(self.workspace_parents),
        }


@dataclass(frozen=True)
class ProjectDiscovery:
    """Read-only recovery result for project hints that did not resolve exactly."""

    status: Literal["resolved", "needs_confirmation", "ambiguous", "not_found"]
    hints: tuple[str, ...]
    candidates: tuple[ProjectCandidate, ...]
    resolution: ProjectResolution | None = None

    def payload(self) -> dict[str, object]:
        candidate_payloads = [candidate.payload() for candidate in self.candidates]
        next_actions: list[dict[str, object]] = []
        if self.status in {"needs_confirmation", "ambiguous"}:
            next_actions.extend(
                {
                    "action": "retry_context",
                    "description": "Retry echome_context with this canonical project ID.",
                    "arguments": {"project_hint": candidate.project.id},
                }
                for candidate in self.candidates
            )
            candidate_ids = {candidate.project.id for candidate in self.candidates}
            workspace_parent_ids = sorted(
                {
                    parent_id
                    for candidate in self.candidates
                    for parent_id in candidate.workspace_parents
                    if parent_id not in candidate_ids
                }
            )
            next_actions.extend(
                {
                    "action": "retry_context",
                    "description": "Retry echome_context with the parent workspace ID.",
                    "arguments": {"project_hint": parent_id},
                }
                for parent_id in workspace_parent_ids
            )
        if self.status in {"resolved", "needs_confirmation"} and len(self.candidates) == 1:
            candidate = self.candidates[0].project
            remote_hint = next(
                (hint for hint in self.hints if _looks_like_git_remote(hint)),
                None,
            )
            if remote_hint is not None:
                try:
                    current_remote = (
                        normalize_project_hint(candidate.git_remote, "git_remote")
                        if candidate.git_remote
                        else None
                    )
                    hinted_remote = normalize_project_hint(remote_hint, "git_remote")
                except ValueError:
                    current_remote = hinted_remote = None
                if hinted_remote is not None and hinted_remote != current_remote:
                    arguments: dict[str, object] = {
                        "project_id": candidate.id,
                        "confirmed": False,
                    }
                    if candidate.git_remote:
                        arguments["git_remote_aliases"] = [remote_hint]
                    else:
                        arguments["git_remote"] = remote_hint
                    next_actions.append(
                        {
                            "action": "confirm_then_update_project_git_identity",
                            "description": (
                                "Preview this Git identity update, then apply it only after the "
                                "user confirms the candidate is the same repository."
                            ),
                            "arguments": arguments,
                        }
                    )
        create_proposal = (
            _project_create_proposal(self.hints) if self.status == "not_found" else None
        )
        if create_proposal is not None:
            next_actions.append(
                {
                    "action": "confirm_then_create_project",
                    "description": "Confirm this is a new project before calling echome_create_project.",
                    "arguments": create_proposal,
                }
            )
        return {
            "schema_version": "echome.project-resolution.v1",
            "status": self.status,
            "input_hints": list(self.hints),
            "auto_resolved": self.resolution is not None,
            "resolution": (
                self.resolution.payload(
                    self.candidates[0].matched_hints[0]
                    if self.candidates and self.candidates[0].matched_hints
                    else self.hints[0]
                )
                if self.resolution is not None
                else None
            ),
            "candidates": candidate_payloads,
            "create_proposal": create_proposal,
            "requires_confirmation": self.status != "resolved",
            "next_actions": next_actions,
        }


@dataclass(frozen=True)
class ProjectGitIdentityUpdate:
    """A server-owned preview or applied update for one project's Git identity."""

    project: Project
    before_git_remote: str | None
    requested_git_remote: str | None
    normalized_git_remote: str | None
    aliases_to_create: tuple[str, ...]
    aliases_to_activate: tuple[str, ...]
    aliases_unchanged: tuple[str, ...]
    aliases_covered_by_primary: tuple[str, ...]
    applied: bool

    @property
    def primary_changed(self) -> bool:
        return (
            self.requested_git_remote is not None
            and self.requested_git_remote != self.before_git_remote
        )

    @property
    def has_changes(self) -> bool:
        return self.primary_changed or bool(self.aliases_to_create or self.aliases_to_activate)

    @property
    def confirmation_token(self) -> str | None:
        if not self.has_changes:
            return None
        token_payload = {
            "project_id": self.project.id,
            "before_git_remote": self.before_git_remote,
            "requested_git_remote": self.requested_git_remote,
            "aliases_to_create": self.aliases_to_create,
            "aliases_to_activate": self.aliases_to_activate,
            "aliases_unchanged": self.aliases_unchanged,
            "aliases_covered_by_primary": self.aliases_covered_by_primary,
        }
        encoded = json.dumps(
            token_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def payload(self) -> dict[str, object]:
        after_git_remote = (
            self.requested_git_remote
            if self.requested_git_remote is not None
            else self.before_git_remote
        )
        if not self.has_changes:
            update_status = "unchanged"
        elif self.applied:
            update_status = "updated"
        else:
            update_status = "confirmation_required"
        return {
            "schema_version": "echome.project-git-identity.v1",
            "status": update_status,
            "requires_confirmation": self.has_changes and not self.applied,
            "confirmation_token": self.confirmation_token,
            "project": {
                "id": self.project.id,
                "name": self.project.name,
                "kind": self.project.kind,
                "description": self.project.description,
                "git_remote": self.project.git_remote,
                "path_patterns": list(self.project.path_patterns or []),
            },
            "normalized_git_remote": self.normalized_git_remote,
            "changes": {
                "git_remote": {
                    "before": self.before_git_remote,
                    "after": after_git_remote,
                    "changed": self.primary_changed,
                },
                "aliases_to_create": list(self.aliases_to_create),
                "aliases_to_activate": list(self.aliases_to_activate),
                "aliases_unchanged": list(self.aliases_unchanged),
                "aliases_covered_by_primary": list(self.aliases_covered_by_primary),
            },
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


def _looks_like_git_remote(value: str) -> bool:
    return "://" in value or value.startswith("git@") or value.endswith(".git")


def _looks_like_path(value: str) -> bool:
    return value.startswith(("/", "./", "../", "~", "\\")) or bool(
        re.match(r"^[A-Za-z]:[\\/]", value)
    )


def infer_alias_types(hint: str) -> list[str]:
    """Return bounded lookup strategies for an untyped client hint."""
    value = hint.strip()
    if _looks_like_git_remote(value):
        return ["git_remote", "client_hint"]
    if _looks_like_path(value):
        return ["path", "client_hint"]
    return ["legacy_id", "name", "client_hint"]


def _identity_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        part.casefold()
        for part in re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value))
        if part
    )


def _identity_variants(value: str, alias_type: str | None = None) -> set[str]:
    clean_value = _normalized_text(value)
    variants = {clean_value}
    if alias_type == "git_remote" or _looks_like_git_remote(clean_value):
        normalized_remote = _normalize_git_remote(clean_value)
        remote_path = normalized_remote.partition("/")[2]
        variants.update({normalized_remote, remote_path, posixpath.basename(remote_path)})
    if alias_type == "path" or _looks_like_path(clean_value):
        path = clean_value.replace("\\", "/")
        wildcard_indexes = [path.find(marker) for marker in ("*", "?", "[")]
        wildcard_indexes = [index for index in wildcard_indexes if index >= 0]
        path = path[: min(wildcard_indexes, default=len(path))].rstrip("/")
        variants.add(posixpath.basename(path))
    elif "/" in clean_value:
        variants.add(posixpath.basename(clean_value.rstrip("/")))
    return {variant for variant in variants if variant}


def _identity_keys(value: str, alias_type: str | None = None) -> set[str]:
    """Build separator-insensitive identity keys without semantic/vector matching."""
    variants = _identity_variants(value, alias_type)
    keys = {"".join(_identity_tokens(item)) for item in variants}
    return {key for key in keys if key}


def _environment_key(value: str) -> str:
    tokens = list(_identity_tokens(value))
    while len(tokens) > 1 and tokens[-1] in ENVIRONMENT_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def _environment_keys(value: str, alias_type: str | None = None) -> set[str]:
    return {
        key
        for variant in _identity_variants(value, alias_type)
        if (key := _environment_key(variant))
    }


def _score_identity_match(
    hint: str,
    candidate_value: str,
    *,
    candidate_type: str | None = None,
) -> tuple[float, str] | None:
    hint_keys = _identity_keys(hint)
    candidate_keys = _identity_keys(candidate_value, candidate_type)
    if not hint_keys or not candidate_keys:
        return None
    exact_matches = hint_keys & candidate_keys
    if exact_matches:
        if max(len(key) for key in exact_matches) >= 4:
            return 0.9, "derived_identity"
        return 0.76, "short_derived_identity"

    environment_hint_keys = _environment_keys(hint)
    environment_candidate_keys = _environment_keys(candidate_value, candidate_type)
    environment_matches = {
        key for key in environment_hint_keys & environment_candidate_keys if len(key) >= 4
    }
    if environment_matches:
        return 0.87, "environment_variant"

    ratios = [
        SequenceMatcher(None, hint_key, candidate_key).ratio()
        for hint_key in hint_keys
        for candidate_key in candidate_keys
        if min(len(hint_key), len(candidate_key)) >= 4
    ]
    best_ratio = max(ratios, default=0.0)
    if best_ratio < 0.72:
        return None
    return round(0.55 + (best_ratio * 0.25), 3), "similar_identity"


def _score_workspace_hint(hint: str, project: Project) -> tuple[float, str] | None:
    if project.kind != "workspace":
        return None
    hint_tokens = {
        token
        for variant in _identity_variants(hint)
        for token in _identity_tokens(variant)
    }
    workspace_tokens = {
        token
        for value in (project.id, project.name)
        for variant in _identity_variants(value)
        for token in _identity_tokens(variant)
        if token not in WORKSPACE_GENERIC_TOKENS and len(token) >= 3
    }
    shared_tokens = hint_tokens & workspace_tokens
    if not shared_tokens:
        return None
    score = 0.7 if max(len(token) for token in shared_tokens) >= 4 else 0.69
    return score, "workspace_identity_token"


def _project_create_proposal(hints: tuple[str, ...]) -> dict[str, object] | None:
    if not hints:
        return None
    preferred = hints[0]
    remote = next(
        (
            hint
            for hint in hints
            if _looks_like_git_remote(hint)
        ),
        None,
    )
    path = next(
        (hint for hint in hints if _looks_like_path(hint)),
        None,
    )
    if remote:
        normalized_remote = _normalize_git_remote(remote)
        remote_path = normalized_remote.partition("/")[2]
        project_id = remote_path or posixpath.basename(normalized_remote)
        name = posixpath.basename(project_id)
    elif path:
        clean_path = path.replace("\\", "/").rstrip("/")
        project_id = name = posixpath.basename(clean_path)
    else:
        name = _normalized_text(preferred)
        project_id = re.sub(r"\s+", "-", name)
    if not project_id or not name:
        return None
    proposal: dict[str, object] = {
        "project_id": project_id[:128],
        "name": name[:256],
        "kind": "repository",
        "git_remote": remote,
        "path_patterns": [],
    }
    if path:
        clean_path = path.replace("\\", "/").rstrip("/")
        proposal["path_patterns"] = [f"{clean_path}/**"]
    return proposal


async def _all_user_projects(session: AsyncSession, user_id: str) -> list[Project]:
    result = await session.execute(select(Project).where(Project.user_id == user_id))
    return list(result.scalars().all())


async def update_project_git_identity(
    session: AsyncSession,
    user_id: str,
    project_hint: str,
    *,
    git_remote: str | None,
    git_remote_aliases: list[str],
    confirmed: bool,
    confirmation_token: str | None = None,
    source: Literal["manual", "ai", "imported", "bootstrap"] = "ai",
) -> ProjectGitIdentityUpdate:
    """Preview or atomically apply a conflict-checked Git identity update."""
    project = (await resolve_project(session, user_id, project_hint)).project
    requested_git_remote = _normalized_text(git_remote) if git_remote is not None else None

    aliases_by_normalized: dict[str, str] = {}
    for alias_value in git_remote_aliases:
        clean_alias = _normalized_text(alias_value)
        normalized_alias = normalize_project_hint(clean_alias, "git_remote")
        aliases_by_normalized.setdefault(normalized_alias, clean_alias)
    if requested_git_remote is None and not aliases_by_normalized:
        raise ValueError("A git_remote or at least one git_remote_alias is required")

    requested_primary_normalized = (
        normalize_project_hint(requested_git_remote, "git_remote")
        if requested_git_remote is not None
        else None
    )
    after_git_remote = requested_git_remote or project.git_remote
    try:
        normalized_after_git_remote = (
            normalize_project_hint(after_git_remote, "git_remote")
            if after_git_remote
            else None
        )
    except ValueError:
        normalized_after_git_remote = None

    requested_normalized_values = set(aliases_by_normalized)
    if requested_primary_normalized is not None:
        requested_normalized_values.add(requested_primary_normalized)

    projects = await _all_user_projects(session, user_id)
    conflicting_project_ids: set[str] = set()
    for other_project in projects:
        if other_project.id == project.id or not other_project.git_remote:
            continue
        try:
            other_normalized = normalize_project_hint(other_project.git_remote, "git_remote")
        except ValueError:
            continue
        if other_normalized in requested_normalized_values:
            conflicting_project_ids.add(other_project.id)

    alias_result = await session.execute(
        select(ProjectAlias).where(
            ProjectAlias.user_id == user_id,
            ProjectAlias.alias_type == "git_remote",
            ProjectAlias.normalized_value.in_(requested_normalized_values),
        )
    )
    existing_aliases = list(alias_result.scalars().all())
    conflicting_project_ids.update(
        alias.canonical_project_id
        for alias in existing_aliases
        if alias.canonical_project_id != project.id
    )
    if conflicting_project_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_GIT_IDENTITY_CONFLICT",
                "message": "Git identity is already assigned to another canonical project",
                "canonical_project_ids": sorted(conflicting_project_ids),
                "normalized_values": sorted(requested_normalized_values),
            },
        )

    existing_aliases_by_normalized = {
        alias.normalized_value: alias
        for alias in existing_aliases
        if alias.canonical_project_id == project.id
    }
    aliases_to_create: list[str] = []
    aliases_to_activate: list[str] = []
    aliases_unchanged: list[str] = []
    aliases_covered_by_primary: list[str] = []
    for normalized_alias, alias_value in aliases_by_normalized.items():
        if normalized_alias == normalized_after_git_remote:
            aliases_covered_by_primary.append(alias_value)
            continue
        existing_alias = existing_aliases_by_normalized.get(normalized_alias)
        if existing_alias is None:
            aliases_to_create.append(alias_value)
        elif existing_alias.status == "active":
            aliases_unchanged.append(existing_alias.alias_value)
        else:
            aliases_to_activate.append(existing_alias.alias_value)

    before_git_remote = project.git_remote
    primary_changed = (
        requested_git_remote is not None and requested_git_remote != before_git_remote
    )
    has_changes = primary_changed or bool(aliases_to_create or aliases_to_activate)
    preview = ProjectGitIdentityUpdate(
        project=project,
        before_git_remote=before_git_remote,
        requested_git_remote=requested_git_remote,
        normalized_git_remote=normalized_after_git_remote,
        aliases_to_create=tuple(aliases_to_create),
        aliases_to_activate=tuple(aliases_to_activate),
        aliases_unchanged=tuple(aliases_unchanged),
        aliases_covered_by_primary=tuple(aliases_covered_by_primary),
        applied=False,
    )
    if confirmed and has_changes:
        expected_token = preview.confirmation_token
        if (
            expected_token is None
            or confirmation_token is None
            or not secrets.compare_digest(confirmation_token, expected_token)
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROJECT_GIT_IDENTITY_PREVIEW_REQUIRED",
                    "message": (
                        "Preview the current Git identity update and confirm its latest token "
                        "before applying"
                    ),
                },
            )
        if primary_changed:
            project.git_remote = requested_git_remote
        aliases_to_activate_set = set(aliases_to_activate)
        for alias in existing_aliases:
            if alias.alias_value in aliases_to_activate_set:
                alias.status = "active"
        for alias_value in aliases_to_create:
            session.add(
                ProjectAlias(
                    user_id=user_id,
                    canonical_project_id=project.id,
                    alias_type="git_remote",
                    alias_value=alias_value,
                    normalized_value=normalize_project_hint(alias_value, "git_remote"),
                    status="active",
                    source=source,
                    confidence=1.0,
                )
            )
        await session.flush()
        return ProjectGitIdentityUpdate(
            project=project,
            before_git_remote=before_git_remote,
            requested_git_remote=requested_git_remote,
            normalized_git_remote=normalized_after_git_remote,
            aliases_to_create=tuple(aliases_to_create),
            aliases_to_activate=tuple(aliases_to_activate),
            aliases_unchanged=tuple(aliases_unchanged),
            aliases_covered_by_primary=tuple(aliases_covered_by_primary),
            applied=True,
        )
    return preview


async def discover_projects(
    session: AsyncSession,
    user_id: str,
    hints: list[str],
    limit: int = 5,
) -> ProjectDiscovery:
    """Resolve or suggest canonical projects without creating aliases or projects."""
    clean_hints = tuple(dict.fromkeys(hint.strip() for hint in hints if hint.strip()))
    if not clean_hints:
        raise HTTPException(status_code=422, detail="At least one project hint is required")

    projects = await _all_user_projects(session, user_id)
    projects_by_id = {project.id: project for project in projects}
    exact_by_project: dict[str, tuple[ProjectResolution, list[str]]] = {}
    ambiguous_ids: set[str] = set()
    unresolved_hints: list[str] = []
    for hint in clean_hints:
        try:
            resolution = await resolve_project(
                session,
                user_id,
                hint,
                project_candidates=projects,
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                unresolved_hints.append(hint)
                continue
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                ambiguous_ids.update(str(item) for item in exc.detail.get("candidates", []))
                continue
            raise
        existing = exact_by_project.get(resolution.project.id)
        if existing is None:
            exact_by_project[resolution.project.id] = (resolution, [hint])
        else:
            existing[1].append(hint)

    exact_ids = set(exact_by_project)
    conflicting_ids = exact_ids | ambiguous_ids
    if (
        len(exact_by_project) == 1
        and not unresolved_hints
        and not (ambiguous_ids - exact_ids)
    ):
        resolution, resolved_hints = next(iter(exact_by_project.values()))
        candidate = ProjectCandidate(
            project=resolution.project,
            confidence=resolution.confidence,
            matched_by=(resolution.matched_by,),
            matched_hints=tuple(resolved_hints),
        )
        return ProjectDiscovery(
            status="resolved",
            hints=clean_hints,
            candidates=(candidate,),
            resolution=resolution,
        )

    if len(conflicting_ids) > 1:
        conflict_candidates = tuple(
            ProjectCandidate(
                project=projects_by_id[project_id],
                confidence=(
                    exact_by_project[project_id][0].confidence
                    if project_id in exact_by_project
                    else 0.75
                ),
                matched_by=(
                    (exact_by_project[project_id][0].matched_by,)
                    if project_id in exact_by_project
                    else ("ambiguous_exact_match",)
                ),
                matched_hints=(
                    tuple(exact_by_project[project_id][1])
                    if project_id in exact_by_project
                    else clean_hints
                ),
            )
            for project_id in sorted(conflicting_ids)
            if project_id in projects_by_id
        )
        return ProjectDiscovery(
            status="ambiguous",
            hints=clean_hints,
            candidates=conflict_candidates[: max(2, limit)],
        )

    alias_result = await session.execute(
        select(ProjectAlias).where(
            ProjectAlias.user_id == user_id,
            ProjectAlias.status.in_(["active", "proposed"]),
        )
    )
    aliases = list(alias_result.scalars().all())
    relation_result = await session.execute(
        select(ProjectRelation).where(
            ProjectRelation.user_id == user_id,
            ProjectRelation.status == "active",
        )
    )
    parent_ids_by_child: dict[str, set[str]] = {}
    for relation in relation_result.scalars().all():
        parent_ids_by_child.setdefault(relation.child_project_id, set()).add(
            relation.parent_project_id
        )

    values_by_project: dict[str, list[tuple[str, str | None, str, float]]] = {
        project.id: [
            (project.id, None, "project_id", 1.0),
            (project.name, None, "project_name", 1.0),
        ]
        for project in projects
    }
    for project in projects:
        if project.git_remote:
            values_by_project[project.id].append(
                (project.git_remote, "git_remote", "project_git_remote", 1.0)
            )
        values_by_project[project.id].extend(
            (pattern, "path", "project_path_pattern", 1.0)
            for pattern in project.path_patterns or []
        )
    for alias in aliases:
        if alias.canonical_project_id not in values_by_project:
            continue
        confidence_cap = 0.88 if alias.status == "active" else 0.79
        values_by_project[alias.canonical_project_id].append(
            (
                alias.alias_value,
                alias.alias_type,
                f"{alias.status}_alias:{alias.alias_type}",
                confidence_cap,
            )
        )

    match_hints = tuple(unresolved_hints) if exact_by_project else clean_hints
    heuristic_candidates: list[ProjectCandidate] = []
    for project in projects:
        best_score = 0.0
        reasons: set[str] = set()
        candidate_hints: set[str] = set()
        for hint in match_hints:
            hint_best = 0.0
            hint_reason = ""
            for value, value_type, source, confidence_cap in values_by_project[project.id]:
                match = _score_identity_match(hint, value, candidate_type=value_type)
                if match is None:
                    continue
                score, reason = match
                score = min(score, confidence_cap)
                if score > hint_best:
                    hint_best = score
                    hint_reason = f"{source}:{reason}"
            workspace_match = _score_workspace_hint(hint, project)
            if workspace_match is not None and workspace_match[0] > hint_best:
                hint_best, hint_reason = workspace_match
            if hint_best:
                best_score = max(best_score, hint_best)
                reasons.add(hint_reason)
                candidate_hints.add(hint)
        if len(candidate_hints) > 1:
            best_score = min(0.95, best_score + 0.02)
        if best_score < 0.68:
            continue
        heuristic_candidates.append(
            ProjectCandidate(
                project=project,
                confidence=round(best_score, 3),
                matched_by=tuple(sorted(reasons)),
                matched_hints=tuple(hint for hint in match_hints if hint in candidate_hints),
                workspace_parents=tuple(sorted(parent_ids_by_child.get(project.id, set()))),
            )
        )

    heuristic_candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.project.id))
    if exact_by_project:
        exact_resolution, resolved_hints = next(iter(exact_by_project.values()))
        exact_candidate = ProjectCandidate(
            project=exact_resolution.project,
            confidence=exact_resolution.confidence,
            matched_by=(exact_resolution.matched_by,),
            matched_hints=tuple(resolved_hints),
            workspace_parents=tuple(
                sorted(parent_ids_by_child.get(exact_resolution.project.id, set()))
            ),
        )
        strong_conflicts = [
            candidate
            for candidate in heuristic_candidates
            if candidate.project.id != exact_resolution.project.id
            and candidate.confidence >= AUTO_RESOLVE_CONFIDENCE
        ]
        if strong_conflicts:
            return ProjectDiscovery(
                status="ambiguous",
                hints=clean_hints,
                candidates=tuple([exact_candidate, *strong_conflicts][: max(2, limit)]),
            )
        supporting_candidates = [
            candidate
            for candidate in heuristic_candidates
            if candidate.project.id != exact_resolution.project.id
        ]
        return ProjectDiscovery(
            status="resolved",
            hints=clean_hints,
            candidates=tuple([exact_candidate, *supporting_candidates][:limit]),
            resolution=exact_resolution,
        )
    if not heuristic_candidates:
        return ProjectDiscovery(status="not_found", hints=clean_hints, candidates=())

    top = heuristic_candidates[0]
    runner_up = heuristic_candidates[1].confidence if len(heuristic_candidates) > 1 else 0.0
    if (
        top.confidence >= AUTO_RESOLVE_CONFIDENCE
        and top.confidence - runner_up >= AUTO_RESOLVE_MARGIN
    ):
        resolution = ProjectResolution(
            project=top.project,
            matched_by=f"discovery:{top.matched_by[0]}",
            confidence=top.confidence,
        )
        return ProjectDiscovery(
            status="resolved",
            hints=clean_hints,
            candidates=tuple(heuristic_candidates[:limit]),
            resolution=resolution,
        )

    status: Literal["needs_confirmation", "ambiguous"] = (
        "ambiguous"
        if len(heuristic_candidates) > 1 and top.confidence - runner_up < AUTO_RESOLVE_MARGIN
        else "needs_confirmation"
    )
    return ProjectDiscovery(
        status=status,
        hints=clean_hints,
        candidates=tuple(
            heuristic_candidates[: max(2, limit) if status == "ambiguous" else limit]
        ),
    )


async def resolve_project(
    session: AsyncSession,
    user_id: str,
    hint: str,
    alias_type: str | None = None,
    project_candidates: list[Project] | None = None,
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

    projects = (
        project_candidates
        if project_candidates is not None
        else await _all_user_projects(session, user_id)
    )
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


def _relative_path_pattern(pattern: str) -> str | None:
    wildcard_indexes = [pattern.find(marker) for marker in ("*", "?", "[")]
    wildcard_indexes = [index for index in wildcard_indexes if index >= 0]
    prefix_end = min(wildcard_indexes, default=len(pattern))
    prefix = pattern[:prefix_end].rstrip("/")
    basename = posixpath.basename(prefix)
    if not basename:
        return None
    return f"{basename}{pattern[len(prefix) :]}"


def project_matches_changed_paths(
    project: Project,
    path_aliases: list[str],
    changed_paths: list[str],
) -> bool:
    """Match absolute or workspace-relative changed paths to one child project."""
    normalized_paths: list[str] = []
    for path in changed_paths:
        try:
            normalized_paths.append(normalize_project_hint(path, "path"))
        except ValueError:
            continue
    if not normalized_paths:
        return False

    roots: list[str] = []
    for value in path_aliases:
        try:
            roots.append(normalize_project_hint(value, "path").rstrip("/"))
        except ValueError:
            continue
    patterns: list[str] = []
    for value in project.path_patterns or []:
        try:
            patterns.append(normalize_project_hint(value, "path"))
        except ValueError:
            continue

    for path in normalized_paths:
        for root in roots:
            if path == root or path.startswith(f"{root}/"):
                return True
            if not path.startswith("/"):
                basename = posixpath.basename(root)
                if path == basename or path.startswith(f"{basename}/"):
                    return True
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
            if not path.startswith("/"):
                relative_pattern = _relative_path_pattern(pattern)
                if relative_pattern and fnmatch.fnmatch(path, relative_pattern):
                    return True
    return False


async def project_context_scope(
    session: AsyncSession,
    user_id: str,
    project: Project,
    changed_paths: list[str],
) -> ProjectContextScope:
    """Resolve memory inheritance without broadening exact Project Knowledge scope."""
    relation_result = await session.execute(
        select(ProjectRelation).where(
            ProjectRelation.user_id == user_id,
            ProjectRelation.status == "active",
            or_(
                ProjectRelation.parent_project_id == project.id,
                ProjectRelation.child_project_id == project.id,
            ),
        )
    )
    relations = list(relation_result.scalars().all())
    inherited_ids = sorted(
        {item.parent_project_id for item in relations if item.child_project_id == project.id}
    )
    child_ids = sorted(
        {item.child_project_id for item in relations if item.parent_project_id == project.id}
    )
    related_ids = sorted(set(inherited_ids) | set(child_ids))
    related_projects: dict[str, Project] = {}
    if related_ids:
        project_result = await session.execute(
            select(Project).where(
                Project.user_id == user_id,
                Project.id.in_(related_ids),
            )
        )
        related_projects = {item.id: item for item in project_result.scalars().all()}

    potential_ids = [project.id, *related_ids]
    alias_result = await session.execute(
        select(ProjectAlias).where(
            ProjectAlias.user_id == user_id,
            ProjectAlias.canonical_project_id.in_(potential_ids),
            ProjectAlias.status == "active",
        )
    )
    aliases = list(alias_result.scalars().all())
    aliases_by_project: dict[str, list[ProjectAlias]] = {
        project_id: [] for project_id in potential_ids
    }
    for alias in aliases:
        aliases_by_project.setdefault(alias.canonical_project_id, []).append(alias)

    selected_child_ids: list[str] = []
    if (project.kind or "repository") == "workspace" and changed_paths:
        for child_id in child_ids:
            child = related_projects.get(child_id)
            if child is None or (child.kind or "repository") != "repository":
                continue
            path_aliases = [
                item.alias_value
                for item in aliases_by_project.get(child_id, [])
                if item.alias_type == "path"
            ]
            if project_matches_changed_paths(child, path_aliases, changed_paths):
                selected_child_ids.append(child_id)

    canonical_ids = tuple(dict.fromkeys([project.id, *inherited_ids, *selected_child_ids]))
    scope_ids_by_project: dict[str, tuple[str, ...]] = {}
    all_scope_ids: set[str] = set()
    for project_id in canonical_ids:
        scope_ids = {project_id}
        scope_ids.update(
            item.alias_value
            for item in aliases_by_project.get(project_id, [])
            if item.alias_type in HISTORY_SCOPE_ALIAS_TYPES
        )
        ordered_scope_ids = tuple(sorted(scope_ids))
        scope_ids_by_project[project_id] = ordered_scope_ids
        all_scope_ids.update(ordered_scope_ids)

    return ProjectContextScope(
        exact_project_id=project.id,
        canonical_project_ids=canonical_ids,
        memory_scope_ids=tuple(sorted(all_scope_ids)),
        inherited_project_ids=tuple(inherited_ids),
        selected_child_project_ids=tuple(selected_child_ids),
        scope_ids_by_project=scope_ids_by_project,
    )


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
