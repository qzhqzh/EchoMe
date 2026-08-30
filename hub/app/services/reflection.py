"""Source fingerprints and evidence contracts for derived project reflections."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory
from app.models.project_knowledge import (
    ProjectArtifact,
    ProjectConstraint,
    ProjectEvent,
)
from app.services.project_identity import project_scope_ids

REFLECTION_SCHEMA_VERSION = "echome.reflect.v1"
SOURCE_ID_KEYS = {
    "memory": "memory_ids",
    "constraint": "constraint_ids",
    "artifact": "artifact_ids",
    "event": "event_ids",
}


class ReflectionSourceChangedError(ValueError):
    """Raised when a submitted reflection no longer matches current source state."""


def _content_hash(*values: str | None) -> str:
    raw = "\n".join(value or "" for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def source_state(source_type: str, item: Any) -> dict[str, Any]:
    """Serialize the mutable fields that determine whether one source is still current."""
    if source_type == "artifact":
        return {
            "type": source_type,
            "id": str(item.id),
            "content_hash": item.content_hash,
            "revision": item.revision,
            "status": item.status,
            "indexed_at": _iso(item.indexed_at),
        }
    if source_type == "constraint":
        return {
            "type": source_type,
            "id": str(item.id),
            "content_hash": _content_hash(item.title, item.statement, item.rationale),
            "version": item.version,
            "status": item.status,
            "valid_to": _iso(item.valid_to),
            "updated_at": _iso(item.updated_at),
        }
    if source_type == "memory":
        return {
            "type": source_type,
            "id": str(item.id),
            "content_hash": _content_hash(item.title, item.content),
            "status": item.status,
            "sleep_state": item.sleep_state,
            "scope_projects": sorted(item.scope_projects or []),
            "updated_at": _iso(item.updated_at),
        }
    if source_type == "event":
        return {
            "type": source_type,
            "id": str(item.id),
            "content_hash": _content_hash(item.title, item.content),
            "occurred_at": _iso(item.occurred_at),
            "created_at": _iso(item.created_at),
        }
    raise ValueError(f"Unsupported reflection source type: {source_type}")


def source_version_token(source_type: str, item: Any) -> str:
    """Return a non-reversible token for one exact source state."""
    canonical = json.dumps(
        source_state(source_type, item),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_reflection_claims(claims: Iterable[Any]) -> str:
    """Render a view exclusively from claims that each carry validated evidence."""
    sections: list[str] = []
    for index, claim in enumerate(claims, 1):
        references = ", ".join(
            f"`{ref.target_type}:{ref.target_id}` ({ref.relation})"
            for ref in claim.evidence_refs
        )
        sections.append(
            f"## Claim {index}\n\n{claim.statement}\n\n"
            f"- Confidence: {claim.confidence:.3f}\n"
            f"- Evidence: {references}"
        )
    return "\n\n".join(sections)


def reflection_request_fingerprint(
    *,
    project_id: str,
    kind: str,
    query: str,
    claims: Iterable[Any],
    source_fingerprint: str | None,
    supersedes_id: uuid.UUID | None,
) -> str:
    """Hash the semantic submit payload for idempotent replay validation."""
    payload = {
        "project_id": project_id,
        "kind": kind,
        "query": query,
        "claims": [item.model_dump(mode="json") for item in claims],
        "source_fingerprint": source_fingerprint,
        "supersedes_id": str(supersedes_id) if supersedes_id else None,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_ids_from_context(context: dict[str, Any]) -> dict[str, list[str]]:
    """Collect authoritative source IDs selected by the context compiler."""
    ids: dict[str, set[str]] = {key: set() for key in SOURCE_ID_KEYS.values()}
    for item in context.get("constraints", []):
        if isinstance(item, dict) and item.get("id"):
            ids["constraint_ids"].add(str(item["id"]))
    for item in context.get("memories", []):
        if isinstance(item, dict) and item.get("id"):
            ids["memory_ids"].add(str(item["id"]))
    for item in context.get("artifacts", []):
        if isinstance(item, dict) and item.get("id"):
            ids["artifact_ids"].add(str(item["id"]))
    for item in context.get("evidence", []):
        if not isinstance(item, dict):
            continue
        if item.get("constraint_id"):
            ids["constraint_ids"].add(str(item["constraint_id"]))
        if item.get("artifact_id"):
            ids["artifact_ids"].add(str(item["artifact_id"]))
    return {key: sorted(values) for key, values in ids.items()}


def normalize_source_ids(source_watermark: dict[str, Any]) -> dict[str, list[uuid.UUID]]:
    """Parse and deduplicate source IDs from an untrusted watermark."""
    normalized: dict[str, list[uuid.UUID]] = {}
    for key in SOURCE_ID_KEYS.values():
        raw_values = source_watermark.get(key, [])
        if not isinstance(raw_values, list):
            raise ReflectionSourceChangedError(f"{key} must be a list")
        try:
            normalized[key] = sorted(
                {uuid.UUID(str(item)) for item in raw_values},
                key=str,
            )
        except (TypeError, ValueError) as exc:
            raise ReflectionSourceChangedError(f"{key} contains an invalid UUID") from exc
    return normalized


async def _load_sources(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    source_ids: dict[str, list[uuid.UUID]],
    lock: bool = False,
) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []

    artifact_ids = source_ids["artifact_ids"]
    if artifact_ids:
        statement = select(ProjectArtifact).where(
            ProjectArtifact.id.in_(artifact_ids),
            ProjectArtifact.user_id == user_id,
            ProjectArtifact.project_id == project_id,
        )
        statement = statement.execution_options(populate_existing=True)
        result = await session.execute(statement.with_for_update() if lock else statement)
        rows = list(result.scalars().all())
        states.extend(source_state("artifact", item) for item in rows)

    constraint_ids = source_ids["constraint_ids"]
    if constraint_ids:
        statement = select(ProjectConstraint).where(
            ProjectConstraint.id.in_(constraint_ids),
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == project_id,
        )
        statement = statement.execution_options(populate_existing=True)
        result = await session.execute(statement.with_for_update() if lock else statement)
        rows = list(result.scalars().all())
        states.extend(source_state("constraint", item) for item in rows)

    memory_ids = source_ids["memory_ids"]
    if memory_ids:
        scope_ids = await project_scope_ids(session, user_id, project_id)
        statement = select(Memory).where(
            Memory.id.in_(memory_ids),
            Memory.user_id == user_id,
            or_(
                Memory.scope_global.is_(True),
                *(Memory.scope_projects.contains([scope_id]) for scope_id in scope_ids),
            ),
        )
        statement = statement.execution_options(populate_existing=True)
        result = await session.execute(statement.with_for_update() if lock else statement)
        rows = list(result.scalars().all())
        states.extend(source_state("memory", item) for item in rows)

    event_ids = source_ids["event_ids"]
    if event_ids:
        statement = select(ProjectEvent).where(
            ProjectEvent.id.in_(event_ids),
            ProjectEvent.user_id == user_id,
            ProjectEvent.project_id == project_id,
        )
        statement = statement.execution_options(populate_existing=True)
        result = await session.execute(statement.with_for_update() if lock else statement)
        rows = list(result.scalars().all())
        states.extend(source_state("event", item) for item in rows)

    expected = {
        (source_type, str(item_id))
        for source_type, key in SOURCE_ID_KEYS.items()
        for item_id in source_ids[key]
    }
    actual = {(item["type"], item["id"]) for item in states}
    if actual != expected:
        raise ReflectionSourceChangedError("one or more reflection sources are missing or out of scope")
    return sorted(states, key=lambda item: (item["type"], item["id"]))


async def build_source_watermark(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    source_ids: dict[str, Iterable[str | uuid.UUID]],
    lock_sources: bool = False,
) -> dict[str, Any]:
    """Build a server-owned fingerprint over exact source versions and statuses."""
    normalized = normalize_source_ids(
        {key: [str(item) for item in source_ids.get(key, [])] for key in SOURCE_ID_KEYS.values()}
    )
    states = await _load_sources(
        session,
        user_id=user_id,
        project_id=project_id,
        source_ids=normalized,
        lock=lock_sources,
    )
    canonical = json.dumps(states, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": REFLECTION_SCHEMA_VERSION,
        "project_id": project_id,
        **{key: [str(item) for item in values] for key, values in normalized.items()},
        "source_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "source_versions": {
            f"{item['type']}:{item['id']}": hashlib.sha256(
                json.dumps(
                    item,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for item in states
        },
        "source_count": len(states),
    }


async def verify_source_watermark(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    source_watermark: dict[str, Any],
) -> dict[str, Any]:
    """Recompute a watermark and reject stale or client-expanded source sets."""
    if source_watermark.get("schema_version") != REFLECTION_SCHEMA_VERSION:
        raise ReflectionSourceChangedError("unsupported reflection watermark schema")
    if source_watermark.get("project_id") != project_id:
        raise ReflectionSourceChangedError("reflection watermark belongs to another project")
    source_ids = normalize_source_ids(source_watermark)
    current = await build_source_watermark(
        session,
        user_id=user_id,
        project_id=project_id,
        source_ids=source_ids,
        lock_sources=True,
    )
    if source_watermark.get("source_fingerprint") != current["source_fingerprint"]:
        raise ReflectionSourceChangedError("reflection sources changed after prepare")
    return current


def validate_claim_sources(
    claims: Iterable[Any],
    source_watermark: dict[str, Any],
) -> None:
    """Require every reflection claim to cite only prepared sources."""
    normalized = normalize_source_ids(source_watermark)
    allowed = {
        (source_type, item_id)
        for source_type, key in SOURCE_ID_KEYS.items()
        for item_id in normalized[key]
    }
    for claim in claims:
        for ref in claim.evidence_refs:
            if (ref.target_type, ref.target_id) not in allowed:
                raise ReflectionSourceChangedError(
                    "reflection claim cites a source outside the prepared context"
                )
