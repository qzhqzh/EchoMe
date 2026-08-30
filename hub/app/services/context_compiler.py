"""Evidence-first project context compilation with reciprocal-rank fusion."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.memory import Memory, Project
from app.models.project_knowledge import (
    ArtifactChunk,
    ConstraintEdge,
    ConstraintEvidence,
    ContextRun,
    KnowledgeView,
    ProjectArtifact,
    ProjectConstraint,
    ProjectEvent,
)
from app.schemas.project_knowledge import ProjectContextRequest
from app.services.content_safety import find_sensitive_content
from app.services.context_completion import completion_contract
from app.services.context_policy import apply_context_policy, record_policy_diagnostic_overhead
from app.services.embedding import get_embedding, get_embeddings
from app.services.project_identity import project_scope_ids
from app.services.reflection import (
    REFLECTION_SCHEMA_VERSION,
    SOURCE_ID_KEYS,
    source_ids_from_context,
    source_version_token,
)
from app.services.token_counter import count_tokens

ACTIVE_CONSTRAINT_STATUSES = {"active", "proposed", "uncertain"}
ACTIVE_MEMORY_STATUSES = {"active", "ai_review"}
RRF_K = 60
QUERY_ALIASES = {
    "迁移": "migration alembic database additive rollback",
    "数据库": "database migration alembic",
    "删除": "delete deleting preserve provenance archive",
    "归档": "archived inactive provenance",
    "替代": "superseded inactive current version",
    "旧约束": "superseded inactive constraint",
    "当前版本": "current version revision",
    "排除": "exclude inactive superseded deprecated",
    "冲突": "conflict conflicts_with contradiction",
    "矛盾": "conflict conflicts_with contradiction",
    "证据": "evidence artifact revision locator",
    "制品": "artifact revision source",
    "同步": "synchronization manifest hash upload",
    "整理": "governance distill provenance archive",
    "睡眠": "sleep candidate proposal",
    "失败": "failure attempt verification",
    "构建": "build test verification",
}
KIND_ALIASES = {
    "functional": "behavior rule 功能规则",
    "nonfunctional": "quality performance reliability 非功能约束",
    "architecture": "architecture boundary dependency 架构边界依赖",
    "process": "workflow migration review verification 流程迁移审核验证",
    "security": "security credential permission 安全凭据权限",
    "data": "data persistence provenance migration 数据持久化来源迁移",
    "compatibility": "compatibility API client backward 兼容接口客户端",
}


@dataclass
class Candidate:
    key: str
    kind: str
    payload: dict[str, Any]
    text: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


def expand_query(text: str) -> str:
    """Add stable cross-language ontology labels without changing the user query."""
    lowered = text.lower()
    aliases = [value for marker, value in QUERY_ALIASES.items() if marker in lowered]
    return " ".join([text, *aliases])


def query_tokens(text: str) -> set[str]:
    """Tokenize English identifiers and overlapping Chinese n-grams."""
    text = expand_query(text)
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9_+#.-]{2,}", text)}
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        tokens.add(chunk)
        for width in (2, 3, 4):
            tokens.update(chunk[index : index + width] for index in range(len(chunk) - width + 1))
    return tokens


def lexical_score(query: set[str], title: str, body: str) -> float:
    if not query:
        return 0.0
    return 4.0 * len(query & query_tokens(title)) + len(query & query_tokens(body))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for embedding vectors, or zero for invalid vectors."""
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return numerator / denominator if denominator else 0.0


def reciprocal_rank_fusion(
    rankings: dict[str, list[str]],
    *,
    k: int = RRF_K,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Fuse independent rankings without assuming their raw scores are calibrated."""
    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)
    for source, keys in rankings.items():
        for rank, key in enumerate(keys, 1):
            scores[key] += 1.0 / (k + rank)
            reasons[key].append(f"{source}:rank_{rank}")
    return dict(scores), dict(reasons)


def split_artifact_content(content: str, *, target_chars: int = 1600) -> list[dict[str, Any]]:
    """Split text on line boundaries and retain stable line locators."""
    if not content:
        return []
    lines = content.splitlines(keepends=True)
    chunks: list[dict[str, Any]] = []
    start = 0
    buffer: list[str] = []
    size = 0
    for index, line in enumerate(lines):
        if buffer and size + len(line) > target_chars:
            text = "".join(buffer).rstrip()
            chunks.append(
                {
                    "content": text,
                    "locator": {"line_start": start + 1, "line_end": index},
                }
            )
            buffer = []
            size = 0
            start = index
        buffer.append(line)
        size += len(line)
    if buffer:
        chunks.append(
            {
                "content": "".join(buffer).rstrip(),
                "locator": {"line_start": start + 1, "line_end": len(lines)},
            }
        )
    return [item for item in chunks if item["content"]]


def constraint_document(item: ProjectConstraint) -> str:
    """Build a portable semantic document from a typed constraint."""
    return "\n".join(
        part
        for part in (
            item.title,
            item.statement,
            item.rationale,
            " ".join(item.tags or []),
            KIND_ALIASES.get(item.kind, item.kind),
            f"status {item.status} stability {item.stability} version {item.version}",
        )
        if part
    )


def _constraint_payload(item: ProjectConstraint) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "statement": item.statement,
        "kind": item.kind,
        "status": item.status,
        "stability": item.stability,
        "confidence": item.confidence,
        "version": item.version,
        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
        "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
    }


def _memory_payload(item: Memory) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "content": item.content,
        "type": item.type,
        "layer": item.layer,
        "status": item.status,
        "updated_at": item.updated_at.isoformat(),
    }


def _artifact_payload(item: ProjectArtifact) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "logical_path": item.logical_path,
        "kind": item.kind,
        "title": item.title,
        "revision": item.revision,
        "content_hash": item.content_hash,
        "status": item.status,
        "indexed_at": item.indexed_at.isoformat(),
    }


def _chunk_payload(item: ArtifactChunk, artifact: ProjectArtifact) -> dict[str, Any]:
    locator = {"logical_path": artifact.logical_path, **(item.locator or {})}
    return {
        "id": str(item.id),
        "evidence_type": "artifact_chunk",
        "artifact_id": str(artifact.id),
        "artifact_revision": artifact.revision,
        "content_hash": item.content_hash,
        "locator": locator,
        "content": item.content[:1200],
    }


def _is_temporally_active(
    item: Any,
    *,
    valid_at: datetime,
    as_of: datetime,
) -> bool:
    created_at = getattr(item, "created_at", None)
    observed_at = getattr(item, "observed_at", None)
    if created_at and created_at > as_of:
        return False
    if observed_at and observed_at > as_of:
        return False
    valid_from = getattr(item, "valid_from", None)
    valid_to = getattr(item, "valid_to", None)
    invalidated_at = getattr(item, "invalidated_at", None)
    return not (
        (valid_from and valid_from > valid_at)
        or (valid_to and valid_to <= valid_at)
        or (invalidated_at and invalidated_at <= as_of)
    )


def _view_is_fresh(
    view: KnowledgeView,
    current_ids: set[str],
    current_source_versions: dict[str, str] | None = None,
) -> bool:
    if view.status != "current":
        return False
    source_ids = set(view.source_watermark.get("artifact_ids", []))
    if source_ids and not source_ids <= current_ids:
        return False
    expected_versions = view.source_watermark.get("source_versions")
    if isinstance(expected_versions, dict) and expected_versions:
        current_versions = current_source_versions or {}
        return all(current_versions.get(key) == value for key, value in expected_versions.items())
    return True


def _view_freshness_contract(view: KnowledgeView) -> str:
    if view.source_watermark.get("schema_version") == REFLECTION_SCHEMA_VERSION:
        return "reflect_v1"
    if view.refresh_mode == "derived":
        return "legacy_artifact_ids"
    return "manual"


def _add_rank(
    rankings: dict[str, list[str]],
    source: str,
    scored: list[tuple[float, str]],
) -> None:
    rankings[source] = [key for score, key in sorted(scored, reverse=True) if score > 0]


def _serialized_tokens(value: Any) -> int:
    return count_tokens(json.dumps(value, ensure_ascii=False, default=str))


def _trim_to_budget(pack: dict[str, Any], budget: int) -> int:
    """Trim diagnostics and low-priority items while preserving evidence for kept facts."""
    pack["token_used"] = 0
    while True:
        used = _serialized_tokens(pack)
        pack["token_used"] = used
        adjusted = _serialized_tokens(pack)
        if adjusted <= budget:
            pack["token_used"] = adjusted
            return adjusted
        trace = pack.get("retrieval_trace", {})
        if trace.get("selection_reasons"):
            trace["selection_reasons"] = {}
            trace["trace_trimmed"] = True
            continue
        if trace.get("ranking_sources"):
            trace.pop("ranking_sources", None)
            trace["trace_trimmed"] = True
            continue
        if pack.get("memories"):
            pack["memories"].pop()
            continue
        evidence_counts: dict[str, int] = defaultdict(int)
        for item in pack.get("evidence", []):
            constraint_id = item.get("constraint_id")
            if constraint_id:
                evidence_counts[constraint_id] += 1
        duplicate_evidence = next(
            (
                index
                for index in range(len(pack.get("evidence", [])) - 1, -1, -1)
                if pack["evidence"][index].get("constraint_id")
                and evidence_counts[pack["evidence"][index]["constraint_id"]] > 1
            ),
            None,
        )
        if duplicate_evidence is not None:
            pack["evidence"].pop(duplicate_evidence)
            continue
        if len(pack.get("stale_warnings", [])) > 5:
            pack["stale_warnings"].pop()
            continue
        standalone_chunks = [
            index
            for index, item in enumerate(pack.get("evidence", []))
            if item.get("evidence_type") == "artifact_chunk"
        ]
        if len(standalone_chunks) > 2:
            pack["evidence"].pop(standalone_chunks[-1])
            continue
        if len(pack.get("stale_warnings", [])) > 1:
            pack["stale_warnings"].pop()
            continue
        if standalone_chunks:
            pack["evidence"].pop(standalone_chunks[-1])
            continue
        must_ids = {
            item.get("id") for item in pack.get("must_include", []) if isinstance(item, dict)
        }
        removable_index = next(
            (
                index
                for index in range(len(pack.get("constraints", [])) - 1, -1, -1)
                if pack["constraints"][index].get("id") not in must_ids
            ),
            None,
        )
        if removable_index is not None:
            removed = pack["constraints"].pop(removable_index)
            pack["evidence"] = [
                item
                for item in pack.get("evidence", [])
                if item.get("constraint_id") != removed.get("id")
            ]
            continue
        if pack.get("stale_warnings"):
            pack["stale_warnings"].pop()
            continue
        referenced_artifacts = {
            item.get("artifact_id") for item in pack.get("evidence", []) if isinstance(item, dict)
        }
        removable_artifact = next(
            (
                index
                for index in range(len(pack.get("artifacts", [])) - 1, -1, -1)
                if pack["artifacts"][index].get("id") not in referenced_artifacts
            ),
            None,
        )
        if removable_artifact is not None:
            pack["artifacts"].pop(removable_artifact)
            continue
        pack["unknowns"] = ["token budget is too small for a useful context pack"]
        pack["task"] = ""
        pack["project"] = {"id": pack["project"]["id"]}
        pack["token_used"] = _serialized_tokens(pack)
        return pack["token_used"]


async def compile_project_context(
    session: AsyncSession,
    project: Project,
    body: ProjectContextRequest,
    user_id: str,
    *,
    include_source_versions: bool = False,
) -> dict[str, Any]:
    """Compile memory, constraints, chunks, graph signals, and freshness warnings."""
    body = body.model_copy(update={"project_id": project.id})
    sensitive_query = bool(find_sensitive_content(body.task))
    if sensitive_query and body.record_run:
        body = body.model_copy(update={"record_run": False, "shadow": True})
    now = datetime.now(timezone.utc)
    as_of = body.as_of or now
    valid_at = body.valid_at or as_of
    query = body.task
    tokens = query_tokens(query)

    constraint_result = await session.execute(
        select(ProjectConstraint).where(
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == body.project_id,
        )
    )
    all_constraints = list(constraint_result.scalars().all())
    successors = {
        item.previous_version_id: item
        for item in all_constraints
        if item.previous_version_id is not None
    }
    constraints = []
    for item in all_constraints:
        status_is_active = item.status in ACTIVE_CONSTRAINT_STATUSES
        if body.as_of and item.status == "superseded":
            successor = successors.get(item.id)
            status_is_active = successor is not None and successor.created_at > as_of
        if status_is_active and _is_temporally_active(item, valid_at=valid_at, as_of=as_of):
            constraints.append(item)

    artifact_result = await session.execute(
        select(ProjectArtifact).where(
            ProjectArtifact.user_id == user_id,
            ProjectArtifact.project_id == body.project_id,
        )
    )
    all_artifacts = list(artifact_result.scalars().all())
    artifacts_by_id = {item.id: item for item in all_artifacts}
    latest_artifacts = [item for item in all_artifacts if item.status == "current"]
    current_by_path = {item.logical_path: item for item in latest_artifacts}
    if body.as_of:
        revisions_by_path: dict[str, list[ProjectArtifact]] = defaultdict(list)
        for item in all_artifacts:
            if item.indexed_at <= as_of:
                revisions_by_path[item.logical_path].append(item)
        current_artifacts = [
            max(items, key=lambda item: (item.revision, item.indexed_at))
            for items in revisions_by_path.values()
        ]
    else:
        current_artifacts = latest_artifacts

    evidence_result = await session.execute(
        select(ConstraintEvidence).where(
            ConstraintEvidence.user_id == user_id,
            ConstraintEvidence.project_id == body.project_id,
        )
    )
    evidence = [
        item
        for item in evidence_result.scalars().all()
        if _is_temporally_active(item, valid_at=valid_at, as_of=as_of)
    ]
    edge_result = await session.execute(
        select(ConstraintEdge).where(
            ConstraintEdge.user_id == user_id,
            ConstraintEdge.project_id == body.project_id,
        )
    )
    edges = [
        item
        for item in edge_result.scalars().all()
        if _is_temporally_active(item, valid_at=valid_at, as_of=as_of)
    ]

    scope_ids = await project_scope_ids(session, user_id, project.id)
    memory_filter = [
        Memory.user_id == user_id,
        Memory.status.in_(ACTIVE_MEMORY_STATUSES),
        or_(
            Memory.scope_global.is_(True),
            *(Memory.scope_projects.contains([scope_id]) for scope_id in scope_ids),
        ),
    ]
    if body.as_of:
        memory_filter.append(Memory.updated_at <= body.as_of)
    memory_result = await session.execute(select(Memory).where(*memory_filter))
    memories = list(memory_result.scalars().all())

    chunk_result = await session.execute(
        select(ArtifactChunk).where(
            ArtifactChunk.user_id == user_id,
            ArtifactChunk.project_id == body.project_id,
            ArtifactChunk.artifact_id.in_([item.id for item in current_artifacts]),
        )
    )
    chunks = list(chunk_result.scalars().all()) if current_artifacts else []

    candidates: dict[str, Candidate] = {}
    for item in constraints:
        key = f"constraint:{item.id}"
        candidates[key] = Candidate(
            key, "constraint", _constraint_payload(item), constraint_document(item)
        )
    for item in memories:
        key = f"memory:{item.id}"
        candidates[key] = Candidate(
            key, "memory", _memory_payload(item), f"{item.title} {item.content}"
        )
    for item in chunks:
        artifact = artifacts_by_id.get(item.artifact_id)
        if artifact is None:
            continue
        key = f"chunk:{item.id}"
        candidates[key] = Candidate(
            key,
            "chunk",
            _chunk_payload(item, artifact),
            f"{artifact.logical_path} {artifact.title} {item.content}",
        )

    rankings: dict[str, list[str]] = {}
    for kind in ("constraint", "memory", "chunk"):
        _add_rank(
            rankings,
            f"lexical_{kind}",
            [
                (lexical_score(tokens, candidate.payload.get("title", ""), candidate.text), key)
                for key, candidate in candidates.items()
                if candidate.kind == kind
            ],
        )

    if current_artifacts and query.strip():
        fts_query = func.plainto_tsquery("simple", query)
        fts_result = await session.execute(
            select(
                ArtifactChunk.id,
                func.ts_rank_cd(ArtifactChunk.search_vector, fts_query).label("rank"),
            )
            .where(
                ArtifactChunk.user_id == user_id,
                ArtifactChunk.project_id == body.project_id,
                ArtifactChunk.artifact_id.in_([item.id for item in current_artifacts]),
                ArtifactChunk.search_vector.op("@@")(fts_query),
            )
            .order_by(text("rank DESC"))
            .limit(body.limit * 3)
        )
        rankings["fts_chunk"] = [f"chunk:{row[0]}" for row in fts_result]

    changed_paths = set(body.changed_paths)
    path_rank: list[tuple[float, str]] = []
    linked_constraint_ids: set[uuid.UUID] = set()
    for item in evidence:
        artifact = artifacts_by_id.get(item.artifact_id)
        if artifact and any(
            artifact.logical_path == path or artifact.logical_path.endswith(path)
            for path in changed_paths
        ):
            linked_constraint_ids.add(item.constraint_id)
    for key, candidate in candidates.items():
        if candidate.kind == "chunk":
            path = candidate.payload["locator"].get("logical_path", "")
            if any(path == item or path.endswith(item) for item in changed_paths):
                path_rank.append((10.0, key))
        elif (
            candidate.kind == "constraint"
            and uuid.UUID(candidate.payload["id"]) in linked_constraint_ids
        ):
            path_rank.append((9.0, key))
    _add_rank(rankings, "changed_path", path_rank)

    constraint_by_id = {item.id: item for item in constraints}
    graph_scores: dict[uuid.UUID, float] = defaultdict(float)
    for edge in edges:
        if edge.source_constraint_id in linked_constraint_ids:
            graph_scores[edge.target_constraint_id] += 2.0
        if edge.target_constraint_id in linked_constraint_ids:
            graph_scores[edge.source_constraint_id] += 2.0
        if edge.relation == "conflicts_with" and (
            "conflict" in query.lower() or "冲突" in query or "矛盾" in query
        ):
            graph_scores[edge.source_constraint_id] += 5.0
            graph_scores[edge.target_constraint_id] += 5.0
    _add_rank(
        rankings,
        "graph",
        [
            (score, f"constraint:{item_id}")
            for item_id, score in graph_scores.items()
            if item_id in constraint_by_id
        ],
    )
    temporal_overview = body.as_of is not None and body.mode == "overview"
    if temporal_overview:
        _add_rank(
            rankings,
            "temporal_scope",
            [
                (
                    2.0 if item.stability == "invariant" else 1.0,
                    f"constraint:{item.id}",
                )
                for item in constraints
            ],
        )

    semantic_scores: dict[str, float] = {}
    query_embedding = None if sensitive_query else await get_embedding(expand_query(query))
    if query_embedding is not None:
        constraint_embeddings: dict[uuid.UUID, list[float]] = {}
        missing_constraints = []
        for item in constraints:
            if item.embedding is not None:
                constraint_embeddings[item.id] = list(item.embedding)
            else:
                missing_constraints.append(item)
        if missing_constraints:
            safe_missing = [
                item
                for item in missing_constraints
                if not find_sensitive_content(constraint_document(item))
            ]
            generated = (
                await get_embeddings([constraint_document(item) for item in safe_missing])
                if safe_missing
                else []
            )
            if generated:
                constraint_embeddings.update(
                    {item.id: vector for item, vector in zip(safe_missing, generated, strict=False)}
                )
        constraint_vector_rank = []
        for item in constraints:
            vector = constraint_embeddings.get(item.id)
            if vector is None:
                continue
            similarity = cosine_similarity(query_embedding, vector)
            key = f"constraint:{item.id}"
            semantic_scores[key] = similarity
            if similarity >= 0.45:
                constraint_vector_rank.append((similarity, key))
        _add_rank(rankings, "vector_constraint", constraint_vector_rank)

        memory_vector_result = await session.execute(
            select(Memory.id, Memory.embedding.cosine_distance(query_embedding).label("distance"))
            .where(*memory_filter, Memory.embedding.isnot(None))
            .order_by("distance")
            .limit(body.limit * 3)
        )
        memory_vector_rank = []
        for row in memory_vector_result:
            similarity = 1.0 - float(row[1])
            key = f"memory:{row[0]}"
            semantic_scores[key] = similarity
            if similarity >= 0.45:
                memory_vector_rank.append((similarity, key))
        _add_rank(rankings, "vector_memory", memory_vector_rank)
        if current_artifacts:
            chunk_vector_result = await session.execute(
                select(
                    ArtifactChunk.id,
                    ArtifactChunk.embedding.cosine_distance(query_embedding).label("distance"),
                )
                .where(
                    ArtifactChunk.user_id == user_id,
                    ArtifactChunk.project_id == body.project_id,
                    ArtifactChunk.artifact_id.in_([item.id for item in current_artifacts]),
                    ArtifactChunk.embedding.isnot(None),
                )
                .order_by("distance")
                .limit(body.limit * 3)
            )
            chunk_vector_rank = []
            for row in chunk_vector_result:
                similarity = 1.0 - float(row[1])
                key = f"chunk:{row[0]}"
                semantic_scores[key] = similarity
                if similarity >= 0.45:
                    chunk_vector_rank.append((similarity, key))
            _add_rank(rankings, "vector_chunk", chunk_vector_rank)

    scores, reasons = reciprocal_rank_fusion(rankings)
    for key, candidate in candidates.items():
        candidate.score = scores.get(key, 0.0)
        candidate.reasons = reasons.get(key, [])
        if key in semantic_scores:
            candidate.reasons.append(f"semantic_similarity:{semantic_scores[key]:.3f}")
        if candidate.kind == "constraint":
            status = candidate.payload["status"]
            candidate.reasons.append(f"status:{status}")

    ranked_candidates = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
    selected = []
    for kind in ("constraint", "memory", "chunk"):
        selected.extend(
            [item for item in ranked_candidates if item.kind == kind and item.score > 0][
                : body.limit
            ]
        )
    must_include = []
    for item in selected:
        if item.kind != "constraint":
            continue
        linked = uuid.UUID(item.payload["id"]) in linked_constraint_ids
        coverage = len(tokens & query_tokens(item.text)) / max(1, len(tokens))
        strong_invariant = item.payload["stability"] == "invariant" and (
            temporal_overview or semantic_scores.get(item.key, 0.0) >= 0.58 or coverage >= 0.20
        )
        if linked or strong_invariant:
            must_include.append(item)

    selected_constraint_ids = {
        uuid.UUID(item.payload["id"]) for item in selected if item.kind == "constraint"
    }
    selected_artifact_ids = {
        uuid.UUID(item.payload["artifact_id"]) for item in selected if item.kind == "chunk"
    }
    evidence_payloads: list[dict[str, Any]] = [
        item.payload for item in selected if item.kind == "chunk"
    ]
    stale_warnings: list[dict[str, Any]] = []
    constraint_rank = {
        uuid.UUID(item.payload["id"]): index
        for index, item in enumerate(selected)
        if item.kind == "constraint"
    }

    def evidence_priority(item: ConstraintEvidence) -> tuple[int, float, str]:
        artifact = artifacts_by_id.get(item.artifact_id)
        if artifact is None:
            return (body.limit + 1, 0.0, "")
        path_score = (
            10.0
            if any(
                artifact.logical_path == path or artifact.logical_path.endswith(path)
                for path in changed_paths
            )
            else 0.0
        )
        relevance = path_score + lexical_score(
            tokens,
            artifact.logical_path,
            f"{artifact.title} {item.excerpt or ''}",
        )
        return (
            constraint_rank.get(item.constraint_id, body.limit + 1),
            -relevance,
            artifact.logical_path,
        )

    for item in sorted(evidence, key=evidence_priority):
        if item.constraint_id not in selected_constraint_ids:
            continue
        artifact = artifacts_by_id.get(item.artifact_id)
        if artifact is None:
            continue
        selected_artifact_ids.add(artifact.id)
        evidence_payloads.append(
            {
                "id": str(item.id),
                "evidence_type": "constraint_evidence",
                "constraint_id": str(item.constraint_id),
                "artifact_id": str(artifact.id),
                "artifact_revision": artifact.revision,
                "relation": item.relation,
                "locator": {"logical_path": artifact.logical_path, **(item.locator or {})},
                "excerpt": item.excerpt,
                "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                "valid_to": item.valid_to.isoformat() if item.valid_to else None,
            }
        )
        current = current_by_path.get(artifact.logical_path)
        if current and current.id != artifact.id:
            stale_warnings.append(
                {
                    "type": "evidence_revision_changed",
                    "constraint_id": str(item.constraint_id),
                    "evidence_artifact_id": str(artifact.id),
                    "current_artifact_id": str(current.id),
                    "logical_path": artifact.logical_path,
                }
            )

    view_result = await session.execute(
        select(KnowledgeView).where(
            KnowledgeView.user_id == user_id,
            KnowledgeView.project_id == body.project_id,
            KnowledgeView.status.in_(["current", "stale"]),
        )
    )
    views = list(view_result.scalars().all())
    current_ids = {str(item.id) for item in current_artifacts}
    expected_source_keys = {
        key
        for view in views
        for key in (view.source_watermark.get("source_versions") or {})
        if isinstance(key, str)
    }
    event_ids: set[uuid.UUID] = set()
    for key in expected_source_keys:
        source_type, separator, raw_id = key.partition(":")
        if source_type != "event" or not separator:
            continue
        try:
            event_ids.add(uuid.UUID(raw_id))
        except ValueError:
            continue
    event_result = (
        await session.execute(
            select(ProjectEvent).where(
                ProjectEvent.user_id == user_id,
                ProjectEvent.project_id == body.project_id,
                ProjectEvent.id.in_(event_ids),
            )
        )
        if event_ids
        else None
    )
    source_items: dict[tuple[str, str], Any] = {
        **{("artifact", str(item.id)): item for item in all_artifacts},
        **{("constraint", str(item.id)): item for item in all_constraints},
        **{("memory", str(item.id)): item for item in memories},
        **{
            ("event", str(item.id)): item
            for item in (event_result.scalars().all() if event_result is not None else [])
        },
    }
    current_source_versions = {}
    for key in expected_source_keys:
        source_type, separator, item_id = key.partition(":")
        source_item = source_items.get((source_type, item_id)) if separator else None
        if source_item is not None:
            current_source_versions[key] = source_version_token(source_type, source_item)
    fresh_views = [
        item for item in views if _view_is_fresh(item, current_ids, current_source_versions)
    ]
    stale_views = [item for item in views if item not in fresh_views]
    stale_warnings.extend(
        {
            "type": "knowledge_view_stale",
            "view_id": str(item.id),
            "kind": item.kind,
            "action": "source_fallback_used",
        }
        for item in stale_views
    )
    if body.mode == "overview":
        for view in fresh_views[:3]:
            evidence_payloads.insert(
                0,
                {
                    "id": str(view.id),
                    "evidence_type": "knowledge_view",
                    "kind": view.kind,
                    "content": view.content,
                    "source_watermark": view.source_watermark,
                    "schema_version": view.schema_version,
                    "producer": view.producer,
                    "freshness_contract": _view_freshness_contract(view),
                },
            )

    conflicts = [
        {
            "edge_id": str(edge.id),
            "source_constraint_id": str(edge.source_constraint_id),
            "target_constraint_id": str(edge.target_constraint_id),
            "reason": edge.reason,
        }
        for edge in edges
        if edge.relation == "conflicts_with"
        and edge.source_constraint_id in selected_constraint_ids
        and edge.target_constraint_id in selected_constraint_ids
    ]

    selected_constraints = []
    selected_memories = []
    for item in selected:
        payload = {**item.payload, "selection_reasons": item.reasons}
        if item.kind == "constraint":
            selected_constraints.append(payload)
        elif item.kind == "memory":
            selected_memories.append(payload)

    artifact_payloads = [
        _artifact_payload(artifacts_by_id[item_id])
        for item_id in selected_artifact_ids
        if item_id in artifacts_by_id
    ]
    unknowns: list[str] = []
    lowered_query = query.lower()
    sensitive_question = any(
        marker in lowered_query
        for marker in ("password", "secret", "credential", "root 密码", "密码", "密钥", "凭据")
    )
    uncertain_future = any(
        marker in lowered_query for marker in ("下个月", "未来", "next month", "future")
    ) and any(marker in lowered_query for marker in ("一定", "保证", "guarantee", "definitely"))
    if sensitive_question:
        unknowns.append("Sensitive credentials are not available from project context.")
    if sensitive_query:
        unknowns.append("Sensitive-looking query text was not embedded or recorded.")
    if uncertain_future:
        unknowns.append("Available evidence cannot guarantee a future release outcome.")
    if not selected:
        unknowns.append("No supported project evidence matched the task.")
    elif not linked_constraint_ids:
        maximum_semantic = max(
            (semantic_scores.get(item.key, 0.0) for item in selected), default=0.0
        )
        maximum_coverage = max(
            (len(tokens & query_tokens(item.text)) / max(1, len(tokens)) for item in selected),
            default=0.0,
        )
        if maximum_semantic < 0.60 and maximum_coverage < 0.20:
            unknowns.append(
                "Retrieved candidates are low-confidence and do not support a definitive answer."
            )
    if selected_constraints and not evidence_payloads:
        unknowns.append("Matched constraints have no retrievable artifact evidence.")
    if sensitive_question or uncertain_future:
        must_include = []

    candidate_counts = {
        "constraints": len(constraints),
        "memories": len(memories),
        "artifact_chunks": len(chunks),
    }
    trace_payload = {
        "strategy": "rrf",
        "rrf_k": RRF_K,
        "candidate_counts": candidate_counts,
        "ranking_sources": {name: len(keys) for name, keys in rankings.items()},
        "selection_reasons": {item.key: item.reasons for item in selected},
        "temporal": {"as_of": as_of.isoformat(), "valid_at": valid_at.isoformat()},
        "sensitive_query_embedding_skipped": sensitive_query,
        "sensitive_constraint_embedding_skipped": sum(
            item.embedding is None and bool(find_sensitive_content(constraint_document(item)))
            for item in constraints
        ),
    }
    run_id = uuid.uuid4() if body.record_run else None
    pack: dict[str, Any] = {
        "project": {"id": project.id, "name": project.name, "description": project.description},
        "task": body.task,
        "mode": body.mode,
        "must_include": [
            {
                "type": item.kind,
                "id": item.payload["id"],
                "reason": (
                    "invariant" if item.payload.get("stability") == "invariant" else "changed_path"
                ),
            }
            for item in must_include
        ],
        "constraints": selected_constraints,
        "memories": selected_memories,
        "artifacts": artifact_payloads,
        "evidence": evidence_payloads,
        "conflicts": conflicts,
        "stale_warnings": stale_warnings,
        "unknowns": unknowns,
        "token_budget": body.token_budget,
        "token_used": 0,
        "retrieval_trace": trace_payload,
        "usage": {
            "constraint_status_note": "proposed and uncertain constraints are context, not confirmed facts",
            "inactive_note": "inactive memories and constraints are excluded from current context",
            "freshness_note": "stale derived views fall back to authoritative evidence",
        },
    }
    if run_id:
        pack["context_run_id"] = str(run_id)
    _trim_to_budget(pack, body.token_budget)
    await apply_context_policy(
        session,
        user_id=user_id,
        context=pack,
        requested_mode=body.policy_mode,
        enforce_enabled=settings.context_policy_enforce_enabled,
        persist_assessments=body.record_run,
        project_id=body.project_id,
        query_mode=body.route or body.mode,
        valid_at=body.valid_at,
    )
    record_policy_diagnostic_overhead(pack)

    if include_source_versions:
        selected_source_ids = source_ids_from_context(pack)
        source_rows: dict[str, dict[str, Any]] = {
            "artifact": {str(item.id): item for item in all_artifacts},
            "constraint": {str(item.id): item for item in all_constraints},
            "memory": {str(item.id): item for item in memories},
        }
        pack["_source_versions"] = {
            f"{source_type}:{item_id}": source_version_token(
                source_type, source_rows[source_type][item_id]
            )
            for source_type, key in SOURCE_ID_KEYS.items()
            if source_type != "event"
            for item_id in selected_source_ids[key]
            if item_id in source_rows[source_type]
        }

    if body.record_run:
        assert run_id is not None
        run = ContextRun(
            id=run_id,
            user_id=user_id,
            project_id=body.project_id,
            query=body.task,
            mode=body.mode,
            changed_paths=body.changed_paths,
            token_budget=body.token_budget,
            token_used=pack["token_used"],
            candidates=candidate_counts,
            selected={
                "constraints": [item["id"] for item in pack["constraints"]],
                "memories": [item["id"] for item in pack["memories"]],
                "evidence": [item["id"] for item in pack["evidence"]],
            },
            trace=trace_payload,
            shadow=body.shadow,
            request_id=body.request_id,
            client=body.client,
            client_version=body.client_version,
            route=body.route,
            fallback=body.fallback,
            error_code=body.error_code,
        )
        session.add(run)
        await session.flush()
        pack["completion_contract"] = completion_contract(str(run_id), shadow=body.shadow)
    return pack
