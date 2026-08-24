"""Evidence-based reliability assessment and shadow context intervention policy."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory, MemoryEdge, MemoryFeedback, Project
from app.models.project_knowledge import (
    ProjectArtifact,
    ProjectConstraint,
    ProjectEvent,
    ReliabilityAssessment,
)
from app.services.token_counter import count_tokens

ASSESSMENT_SCHEMA_VERSION = 1
ASSESSMENT_PRODUCER = "echome.rules.v1"
INACTIVE_MEMORY_STATUSES = {"archived", "deprecated"}
INACTIVE_CONSTRAINT_STATUSES = {"superseded", "deprecated"}
VOLATILE_TAGS = {"volatile", "temporary", "current-state", "short-lived", "time-sensitive"}
STABLE_TAGS = {"stable", "core", "identity", "guardrail", "invariant", "red-line"}
EPISODIC_TAGS = {"event", "incident", "failure", "deploy", "release", "test-result"}
TEMPORAL_TERMS = {
    "current version",
    "latest version",
    "currently",
    "today",
    "tomorrow",
    "this week",
    "当前版本",
    "最新版本",
    "目前",
    "今天",
    "明天",
    "本周",
    "临时",
    "暂时",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _days_since(value: datetime | None, now: datetime) -> int | None:
    normalized = _as_utc(value)
    return max(0, (now - normalized).days) if normalized else None


def _latest(*values: datetime | None) -> datetime | None:
    normalized = [
        value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        for value in values
        if value is not None
    ]
    return max(normalized) if normalized else None


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _memory_class(memory: Memory) -> tuple[str, list[str]]:
    tags = {str(tag).lower() for tag in memory.tags or []}
    text = f"{memory.title} {memory.content[:1200]}".lower()
    reasons: list[str] = []
    if memory.is_core and (memory.type in {"identity", "guardrail"} or tags & STABLE_TAGS):
        reasons.append("core_stable_memory")
        return "invariant", reasons
    if tags & VOLATILE_TAGS or any(term in text for term in TEMPORAL_TERMS):
        reasons.append("explicit_temporal_signal")
        return "volatile", reasons
    if tags & EPISODIC_TAGS:
        reasons.append("episodic_tag")
        return "episodic", reasons
    if memory.scope_projects or memory.type in {"project", "stack", "decision"}:
        reasons.append("project_or_environment_scope")
        return "environment_bound", reasons
    if memory.type in {"identity", "guardrail", "method", "style", "template", "reasoning"}:
        reasons.append("durable_memory_type")
        return "durable", reasons
    reasons.append("no_stability_evidence")
    return "unknown", reasons


def _intervention(
    support_state: str,
    *,
    mode: str,
    has_evidence: bool,
) -> dict[str, Any]:
    if support_state == "current_supported":
        action = "inject"
    elif support_state == "historical":
        action = "inject_with_warning" if mode == "temporal" else "silent"
    elif support_state == "needs_verification":
        action = "expand" if has_evidence else "inject_with_warning"
    elif support_state in {"conflicting", "dormant_scope"}:
        action = "inject_with_warning"
    else:
        action = "abstain"
    return {
        "action": action,
        "include": action not in {"silent", "abstain"},
        "reason": f"support_state:{support_state}",
    }


def record_policy_diagnostic_overhead(context: dict[str, Any]) -> None:
    """Account for policy metadata without changing the context selection budget."""
    policy = context.get("context_policy")
    if not isinstance(policy, dict):
        return
    policy["budget_accounting"] = "diagnostics_excluded_from_token_used"
    policy["diagnostic_token_overhead"] = 0
    for _ in range(3):
        neutral = deepcopy(context)
        neutral.pop("context_policy", None)
        neutral.get("retrieval_trace", {}).pop("context_policy", None)
        for key in ("memories", "constraints"):
            for item in neutral.get(key, []):
                if isinstance(item, dict):
                    item.pop("reliability", None)
                    item.pop("intervention", None)
        overhead = max(0, count_tokens(str(context)) - count_tokens(str(neutral)))
        if policy["diagnostic_token_overhead"] == overhead:
            break
        policy["diagnostic_token_overhead"] = overhead


async def _project_activity(
    session: AsyncSession,
    user_id: str,
    project_ids: set[str],
) -> dict[str, datetime]:
    if not project_ids:
        return {}
    activity: dict[str, datetime] = {}
    project_result = await session.execute(
        select(Project.id, Project.updated_at).where(
            Project.user_id == user_id,
            Project.id.in_(project_ids),
        )
    )
    for project_id, updated_at in project_result.all():
        if updated_at:
            activity[project_id] = (
                updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
            )

    event_result = await session.execute(
        select(
            ProjectEvent.project_id,
            func.max(func.coalesce(ProjectEvent.occurred_at, ProjectEvent.created_at)),
        )
        .where(ProjectEvent.user_id == user_id, ProjectEvent.project_id.in_(project_ids))
        .group_by(ProjectEvent.project_id)
    )
    artifact_result = await session.execute(
        select(ProjectArtifact.project_id, func.max(ProjectArtifact.indexed_at))
        .where(ProjectArtifact.user_id == user_id, ProjectArtifact.project_id.in_(project_ids))
        .group_by(ProjectArtifact.project_id)
    )
    for project_id, occurred_at in [*event_result.all(), *artifact_result.all()]:
        latest = _latest(activity.get(project_id), occurred_at)
        if latest:
            activity[project_id] = latest
    return activity


async def _load_memory_signals(
    session: AsyncSession,
    user_id: str,
    memory_ids: set[uuid.UUID],
) -> tuple[
    dict[uuid.UUID, list[MemoryEdge]],
    dict[uuid.UUID, list[MemoryFeedback]],
]:
    edges_by_memory: dict[uuid.UUID, list[MemoryEdge]] = defaultdict(list)
    feedback_by_memory: dict[uuid.UUID, list[MemoryFeedback]] = defaultdict(list)
    if not memory_ids:
        return edges_by_memory, feedback_by_memory
    edge_result = await session.execute(
        select(MemoryEdge).where(
            MemoryEdge.user_id == user_id,
            or_(
                MemoryEdge.source_memory_id.in_(memory_ids),
                MemoryEdge.target_memory_id.in_(memory_ids),
            ),
        )
    )
    for edge in edge_result.scalars().all():
        if edge.source_memory_id in memory_ids:
            edges_by_memory[edge.source_memory_id].append(edge)
        if edge.target_memory_id in memory_ids:
            edges_by_memory[edge.target_memory_id].append(edge)
    feedback_result = await session.execute(
        select(MemoryFeedback).where(
            MemoryFeedback.user_id == user_id,
            MemoryFeedback.memory_id.in_(memory_ids),
        )
    )
    for item in feedback_result.scalars().all():
        feedback_by_memory[item.memory_id].append(item)
    return edges_by_memory, feedback_by_memory


def _assess_memory(
    memory: Memory,
    *,
    edges: list[MemoryEdge],
    feedback: list[MemoryFeedback],
    activity: dict[str, datetime],
    now: datetime,
) -> dict[str, Any]:
    assessment_class, reasons = _memory_class(memory)
    evidence_refs: list[dict[str, str]] = []
    edge_relations = {edge.relation for edge in edges}
    is_superseded_source = any(
        (edge.relation == "superseded_by" and edge.source_memory_id == memory.id)
        or (edge.relation == "supersedes" and edge.target_memory_id == memory.id)
        for edge in edges
    )
    for edge in sorted(edges, key=lambda item: str(item.id)):
        other_id = (
            edge.target_memory_id if edge.source_memory_id == memory.id else edge.source_memory_id
        )
        evidence_refs.append(
            {
                "type": "memory_edge",
                "id": str(edge.id),
                "relation": edge.relation,
                "other_memory_id": str(other_id),
            }
        )
    feedback_counts = Counter(item.rating for item in feedback)
    feedback_latest = _latest(*(item.created_at for item in feedback))
    project_activity = _latest(*(activity.get(item) for item in memory.scope_projects or []))
    project_activity_age = _days_since(project_activity, now)

    if memory.status in INACTIVE_MEMORY_STATUSES or memory.sleep_state == "superseded":
        support_state = "historical"
        reasons.append(f"inactive:{memory.status}:{memory.sleep_state}")
    elif memory.superseded_by or is_superseded_source:
        support_state = "historical"
        reasons.append("superseded")
    elif "conflicts_with" in edge_relations or feedback_counts["conflicting"]:
        support_state = "conflicting"
        reasons.append("explicit_conflict")
    elif feedback_counts["wrong"] or feedback_counts["outdated"]:
        support_state = "needs_verification"
        reasons.append("negative_feedback")
    elif assessment_class == "volatile":
        support_state = "needs_verification"
        reasons.append("volatile_requires_verification")
    elif (
        assessment_class == "environment_bound"
        and project_activity_age is not None
        and project_activity_age >= 180
    ):
        support_state = "dormant_scope"
        reasons.append("project_dormant_not_stale")
    else:
        support_state = "current_supported"
        reasons.append("no_invalidating_evidence")

    confidence = {
        "historical": 0.98,
        "conflicting": 0.9,
        "needs_verification": 0.78,
        "dormant_scope": 0.7,
        "current_supported": {
            "invariant": 0.92,
            "durable": 0.84,
            "environment_bound": 0.74,
            "episodic": 0.72,
            "unknown": 0.56,
        }.get(assessment_class, 0.56),
    }[support_state]
    watermark = {
        "updated_at": memory.updated_at.isoformat(),
        "status": memory.status,
        "sleep_state": memory.sleep_state,
        "edge_ids": sorted(str(edge.id) for edge in edges),
        "feedback_latest": feedback_latest.isoformat() if feedback_latest else None,
        "feedback_counts": dict(sorted(feedback_counts.items())),
        "project_activity_at": project_activity.isoformat() if project_activity else None,
    }
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "classification": assessment_class,
        "support_state": support_state,
        "confidence": round(float(confidence), 2),
        "reason_codes": sorted(set(reasons)),
        "evidence_refs": evidence_refs,
        "source_watermark": watermark,
        "producer": ASSESSMENT_PRODUCER,
        "assessed_at": now.isoformat(),
    }


def _assess_constraint(
    constraint: ProjectConstraint,
    *,
    conflicts: set[uuid.UUID],
    stale_constraints: set[uuid.UUID],
    evidence_refs: list[dict[str, Any]],
    project_activity: datetime | None,
    valid_at: datetime,
    now: datetime,
) -> dict[str, Any]:
    valid_from = _as_utc(constraint.valid_from)
    valid_to = _as_utc(constraint.valid_to)
    if constraint.stability == "invariant":
        assessment_class = "invariant"
    elif constraint.stability == "temporary":
        assessment_class = "volatile"
    else:
        assessment_class = "environment_bound"
    reasons = [f"constraint_stability:{constraint.stability}"]
    if constraint.status in INACTIVE_CONSTRAINT_STATUSES:
        support_state = "historical"
        reasons.append(f"inactive:{constraint.status}")
    elif valid_to is not None and valid_to <= valid_at:
        support_state = "historical"
        reasons.append("validity_window_ended")
    elif valid_from is not None and valid_from > valid_at:
        support_state = "historical"
        reasons.append("validity_window_not_started")
    elif constraint.id in conflicts:
        support_state = "conflicting"
        reasons.append("explicit_conflict")
    elif constraint.status in {"proposed", "uncertain"}:
        support_state = "needs_verification"
        reasons.append(f"status:{constraint.status}")
    elif constraint.id in stale_constraints:
        support_state = "needs_verification"
        reasons.append("source_revision_changed")
    elif (
        assessment_class == "environment_bound"
        and (age := _days_since(project_activity, now)) is not None
        and age >= 180
    ):
        support_state = "dormant_scope"
        reasons.append("project_dormant_not_stale")
    else:
        support_state = "current_supported"
        reasons.append("no_invalidating_evidence")
    confidence = {
        "historical": 0.98,
        "conflicting": 0.9,
        "needs_verification": 0.82,
        "dormant_scope": 0.72,
        "current_supported": 0.93 if assessment_class == "invariant" else 0.8,
    }[support_state]
    watermark = {
        "version": constraint.version,
        "status": constraint.status,
        "updated_at": constraint.updated_at.isoformat(),
        "last_verified_at": (
            constraint.last_verified_at.isoformat() if constraint.last_verified_at else None
        ),
        "valid_from": constraint.valid_from.isoformat() if constraint.valid_from else None,
        "valid_to": constraint.valid_to.isoformat() if constraint.valid_to else None,
        "project_activity_at": project_activity.isoformat() if project_activity else None,
    }
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "classification": assessment_class,
        "support_state": support_state,
        "confidence": confidence,
        "reason_codes": sorted(set(reasons)),
        "evidence_refs": evidence_refs,
        "source_watermark": watermark,
        "producer": ASSESSMENT_PRODUCER,
        "assessed_at": now.isoformat(),
    }


async def _persist_assessments(
    session: AsyncSession,
    user_id: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    values: list[dict[str, Any]] = []
    for row in rows:
        reliability = row["reliability"]
        fingerprint_payload = {
            "classification": reliability["classification"],
            "support_state": reliability["support_state"],
            "reason_codes": reliability["reason_codes"],
            "evidence_refs": reliability["evidence_refs"],
            "source_watermark": reliability["source_watermark"],
            "producer": reliability["producer"],
            "schema_version": reliability["schema_version"],
        }
        values.append(
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "project_id": row.get("project_id"),
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "assessment_class": reliability["classification"],
                "support_state": reliability["support_state"],
                "confidence": reliability["confidence"],
                "reason_codes": reliability["reason_codes"],
                "evidence_refs": reliability["evidence_refs"],
                "source_watermark": reliability["source_watermark"],
                "source_fingerprint": _fingerprint(fingerprint_payload),
                "producer": reliability["producer"],
                "schema_version": reliability["schema_version"],
                "assessed_at": _utcnow(),
            }
        )
    await session.execute(
        pg_insert(ReliabilityAssessment)
        .values(values)
        .on_conflict_do_nothing(
            index_elements=["user_id", "subject_type", "subject_id", "source_fingerprint"]
        )
    )


async def apply_context_policy(
    session: AsyncSession,
    *,
    user_id: str,
    context: dict[str, Any],
    requested_mode: str,
    enforce_enabled: bool,
    persist_assessments: bool,
    project_id: str | None = None,
    query_mode: str = "personal",
    valid_at: datetime | None = None,
) -> dict[str, Any]:
    """Attach reliability and intervention decisions without rewriting source data."""
    effective_mode = (
        "enforce" if requested_mode == "enforce" and enforce_enabled else requested_mode
    )
    if requested_mode == "enforce" and not enforce_enabled:
        effective_mode = "shadow"
    if effective_mode == "off":
        context["context_policy"] = {
            "schema_version": 1,
            "requested_mode": requested_mode,
            "effective_mode": "off",
            "enforced": False,
            "decision_counts": {},
        }
        return context

    now = _utcnow()
    memory_payloads = [item for item in context.get("memories", []) if item.get("id")]
    memory_ids = {uuid.UUID(str(item["id"])) for item in memory_payloads}
    memories: dict[uuid.UUID, Memory] = {}
    if memory_ids:
        memory_result = await session.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.id.in_(memory_ids))
        )
        memories = {memory_item.id: memory_item for memory_item in memory_result.scalars().all()}
    edges, feedback = await _load_memory_signals(session, user_id, memory_ids)

    constraint_payloads = [item for item in context.get("constraints", []) if item.get("id")]
    constraint_ids = {uuid.UUID(str(item["id"])) for item in constraint_payloads}
    constraints: dict[uuid.UUID, ProjectConstraint] = {}
    if constraint_ids:
        constraint_result = await session.execute(
            select(ProjectConstraint).where(
                ProjectConstraint.user_id == user_id,
                ProjectConstraint.id.in_(constraint_ids),
            )
        )
        constraints = {
            constraint_item.id: constraint_item
            for constraint_item in constraint_result.scalars().all()
        }

    project_ids: set[str] = {project_id} if project_id else set()
    for memory in memories.values():
        project_ids.update(memory.scope_projects or [])
    activity = await _project_activity(session, user_id, project_ids)
    project_activity = activity.get(project_id) if project_id else None

    conflicts: set[uuid.UUID] = set()
    for item in context.get("conflicts", []):
        for key in ("source_constraint_id", "target_constraint_id"):
            if item.get(key):
                conflicts.add(uuid.UUID(str(item[key])))
    stale_constraints = {
        uuid.UUID(str(item["constraint_id"]))
        for item in context.get("stale_warnings", [])
        if item.get("constraint_id")
    }
    constraint_evidence: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for item in context.get("evidence", []):
        if item.get("constraint_id"):
            constraint_evidence[uuid.UUID(str(item["constraint_id"]))].append(
                {
                    key: item[key]
                    for key in (
                        "id",
                        "evidence_type",
                        "artifact_id",
                        "artifact_revision",
                        "relation",
                    )
                    if item.get(key) is not None
                }
            )

    persistence_rows: list[dict[str, Any]] = []
    decision_counts: Counter[str] = Counter()
    for payload in memory_payloads:
        memory_id = uuid.UUID(str(payload["id"]))
        selected_memory = memories.get(memory_id)
        if selected_memory is None:
            continue
        reliability = _assess_memory(
            selected_memory,
            edges=edges[memory_id],
            feedback=feedback[memory_id],
            activity=activity,
            now=now,
        )
        intervention = _intervention(
            reliability["support_state"],
            mode=query_mode,
            has_evidence=bool(reliability["evidence_refs"]),
        )
        payload["reliability"] = reliability
        payload["intervention"] = intervention
        decision_counts[intervention["action"]] += 1
        persistence_rows.append(
            {
                "subject_type": "memory",
                "subject_id": memory_id,
                "project_id": project_id
                or (
                    selected_memory.scope_projects[0]
                    if len(selected_memory.scope_projects or []) == 1
                    else None
                ),
                "reliability": reliability,
            }
        )

    effective_valid_at = _as_utc(valid_at) or now
    for payload in constraint_payloads:
        constraint_id = uuid.UUID(str(payload["id"]))
        constraint = constraints.get(constraint_id)
        if constraint is None:
            continue
        reliability = _assess_constraint(
            constraint,
            conflicts=conflicts,
            stale_constraints=stale_constraints,
            evidence_refs=constraint_evidence[constraint_id],
            project_activity=project_activity,
            valid_at=effective_valid_at,
            now=now,
        )
        intervention = _intervention(
            reliability["support_state"],
            mode=query_mode,
            has_evidence=bool(reliability["evidence_refs"]),
        )
        payload["reliability"] = reliability
        payload["intervention"] = intervention
        decision_counts[intervention["action"]] += 1
        persistence_rows.append(
            {
                "subject_type": "constraint",
                "subject_id": constraint_id,
                "project_id": constraint.project_id,
                "reliability": reliability,
            }
        )

    excluded: dict[str, list[str]] = {"memories": [], "constraints": []}
    if effective_mode == "enforce":
        for key in ("memories", "constraints"):
            retained = []
            for item in context.get(key, []):
                intervention = item.get("intervention", {})
                if intervention.get("include", True):
                    retained.append(item)
                elif item.get("id"):
                    excluded[key].append(str(item["id"]))
            context[key] = retained
        retained_constraint_ids = {
            str(item["id"]) for item in context.get("constraints", []) if item.get("id")
        }
        context["must_include"] = [
            item
            for item in context.get("must_include", [])
            if item.get("type") != "constraint" or str(item.get("id")) in retained_constraint_ids
        ]
        context["evidence"] = [
            item
            for item in context.get("evidence", [])
            if not item.get("constraint_id")
            or str(item["constraint_id"]) in retained_constraint_ids
        ]
        context["conflicts"] = [
            item
            for item in context.get("conflicts", [])
            if str(item.get("source_constraint_id")) in retained_constraint_ids
            and str(item.get("target_constraint_id")) in retained_constraint_ids
        ]
        context["stale_warnings"] = [
            item
            for item in context.get("stale_warnings", [])
            if not item.get("constraint_id")
            or str(item["constraint_id"]) in retained_constraint_ids
        ]
        if any(excluded.values()):
            context.setdefault("unknowns", []).append(
                "Context policy withheld historical or unsupported items; inspect the policy trace."
            )

    policy = {
        "schema_version": 1,
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "enforced": effective_mode == "enforce",
        "decision_counts": dict(sorted(decision_counts.items())),
        "would_exclude": {
            "memories": [
                str(item["id"])
                for item in memory_payloads
                if not item.get("intervention", {}).get("include", True)
            ],
            "constraints": [
                str(item["id"])
                for item in constraint_payloads
                if not item.get("intervention", {}).get("include", True)
            ],
        },
        "excluded": excluded,
        "source_mutation": "none",
    }
    if requested_mode == "enforce" and not enforce_enabled:
        policy["fallback_reason"] = "context_policy_enforce_disabled"
    context["context_policy"] = policy
    context.setdefault("retrieval_trace", {})["context_policy"] = policy
    if persist_assessments:
        await _persist_assessments(session, user_id, persistence_rows)
    return context
