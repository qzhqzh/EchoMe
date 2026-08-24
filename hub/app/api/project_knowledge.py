"""Project constraint graph, artifact sync, and AI context APIs."""

import hashlib
import json
import re
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.config import settings
from app.core.database import get_session
from app.models.memory import Memory, Project
from app.models.project_knowledge import (
    ArtifactChunk,
    AutomationProposalRun,
    ConstraintEdge,
    ConstraintEvidence,
    ConstraintRevalidationProposal,
    ContextQualitySnapshot,
    ContextRun,
    EventLink,
    KnowledgeView,
    ProjectArtifact,
    ProjectConstraint,
    ProjectEvent,
)
from app.schemas.project_knowledge import (
    ArtifactChunkRebuildRequest,
    ArtifactSyncApplyRequest,
    ArtifactSyncCheckRequest,
    AutomationProposalRunCreate,
    ConstraintCreate,
    ConstraintEdgeCreate,
    ConstraintEmbeddingRebuildRequest,
    ConstraintEvidenceCreate,
    ConstraintPatch,
    ContextQualityEvalRequest,
    ContextQualitySnapshotCreate,
    KnowledgeViewCreate,
    ProjectContextRequest,
    ProjectEventCreate,
    ProjectImpactRequest,
    ProjectPreflightRequest,
    RevalidationApplyRequest,
    RevalidationProposalCreate,
    ScaleReplayEvalRequest,
)
from app.services.context_compiler import (
    compile_project_context,
    constraint_document,
    split_artifact_content,
)
from app.services.context_quality_eval import (
    evaluate_context_quality,
    evaluate_scale_reliability,
    load_context_quality_cases,
)
from app.services.embedding import get_embedding, get_embeddings
from app.services.project_identity import resolve_project
from app.services.quality_automation import evaluate_automation_gate
from app.services.token_counter import count_tokens

router = APIRouter(prefix="/project-knowledge", tags=["project-knowledge"])
ACTIVE_CONSTRAINT_STATUSES = {"active", "proposed", "uncertain"}
CONSTRAINT_REVISION_FIELDS = {
    "title",
    "statement",
    "rationale",
    "kind",
    "stability",
    "tags",
    "valid_from",
    "valid_to",
}


async def _require_project(session: AsyncSession, project_id: str, user_id: str) -> Project:
    return (await resolve_project(session, user_id, project_id)).project


def _artifact_payload(artifact: ProjectArtifact, include_content: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(artifact.id),
        "project_id": artifact.project_id,
        "logical_path": artifact.logical_path,
        "kind": artifact.kind,
        "title": artifact.title,
        "content_hash": artifact.content_hash,
        "hash_algorithm": artifact.hash_algorithm,
        "size_bytes": artifact.size_bytes,
        "revision": artifact.revision,
        "source_uri": artifact.source_uri,
        "metadata": artifact.artifact_metadata,
        "status": artifact.status,
        "supersedes_id": str(artifact.supersedes_id) if artifact.supersedes_id else None,
        "indexed_at": artifact.indexed_at.isoformat(),
    }
    if include_content:
        payload["content"] = artifact.content
    return payload


def _constraint_payload(constraint: ProjectConstraint) -> dict[str, Any]:
    return {
        "id": str(constraint.id),
        "project_id": constraint.project_id,
        "title": constraint.title,
        "statement": constraint.statement,
        "rationale": constraint.rationale,
        "kind": constraint.kind,
        "status": constraint.status,
        "stability": constraint.stability,
        "confidence": constraint.confidence,
        "source": constraint.source,
        "tags": constraint.tags,
        "version": constraint.version,
        "previous_version_id": (
            str(constraint.previous_version_id) if constraint.previous_version_id else None
        ),
        "valid_from": constraint.valid_from.isoformat() if constraint.valid_from else None,
        "valid_to": constraint.valid_to.isoformat() if constraint.valid_to else None,
        "last_verified_at": (
            constraint.last_verified_at.isoformat() if constraint.last_verified_at else None
        ),
        "superseded_by": str(constraint.superseded_by) if constraint.superseded_by else None,
        "created_at": constraint.created_at.isoformat(),
        "updated_at": constraint.updated_at.isoformat(),
    }


def _edge_payload(edge: ConstraintEdge) -> dict[str, Any]:
    return {
        "id": str(edge.id),
        "source_constraint_id": str(edge.source_constraint_id),
        "target_constraint_id": str(edge.target_constraint_id),
        "relation": edge.relation,
        "reason": edge.reason,
        "created_by": edge.created_by,
        "observed_at": edge.observed_at.isoformat() if edge.observed_at else None,
        "valid_from": edge.valid_from.isoformat() if edge.valid_from else None,
        "valid_to": edge.valid_to.isoformat() if edge.valid_to else None,
        "invalidated_at": edge.invalidated_at.isoformat() if edge.invalidated_at else None,
        "source_metadata": edge.source_metadata,
        "created_at": edge.created_at.isoformat(),
    }


def _evidence_payload(evidence: ConstraintEvidence) -> dict[str, Any]:
    return {
        "id": str(evidence.id),
        "constraint_id": str(evidence.constraint_id),
        "artifact_id": str(evidence.artifact_id),
        "relation": evidence.relation,
        "locator": evidence.locator,
        "excerpt": evidence.excerpt,
        "created_by": evidence.created_by,
        "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
        "valid_from": evidence.valid_from.isoformat() if evidence.valid_from else None,
        "valid_to": evidence.valid_to.isoformat() if evidence.valid_to else None,
        "invalidated_at": (
            evidence.invalidated_at.isoformat() if evidence.invalidated_at else None
        ),
        "source_metadata": evidence.source_metadata,
        "created_at": evidence.created_at.isoformat(),
    }


def _chunk_payload(chunk: ArtifactChunk, artifact: ProjectArtifact) -> dict[str, Any]:
    return {
        "id": str(chunk.id),
        "project_id": chunk.project_id,
        "artifact_id": str(chunk.artifact_id),
        "artifact_revision": artifact.revision,
        "ordinal": chunk.ordinal,
        "locator": {"logical_path": artifact.logical_path, **(chunk.locator or {})},
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "token_count": chunk.token_count,
        "has_embedding": chunk.embedding is not None,
        "schema_version": chunk.schema_version,
        "producer": chunk.producer,
        "created_at": chunk.created_at.isoformat(),
    }


def _view_payload(view: KnowledgeView) -> dict[str, Any]:
    return {
        "id": str(view.id),
        "project_id": view.project_id,
        "kind": view.kind,
        "query": view.query,
        "content": view.content,
        "source_watermark": view.source_watermark,
        "refresh_mode": view.refresh_mode,
        "status": view.status,
        "token_count": view.token_count,
        "schema_version": view.schema_version,
        "producer": view.producer,
        "supersedes_id": str(view.supersedes_id) if view.supersedes_id else None,
        "stale_at": view.stale_at.isoformat() if view.stale_at else None,
        "created_at": view.created_at.isoformat(),
    }


def _proposal_payload(item: ConstraintRevalidationProposal) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "project_id": item.project_id,
        "constraint_id": str(item.constraint_id),
        "base_version": item.base_version,
        "reason": item.reason,
        "proposal": item.proposal,
        "source_refs": item.source_refs,
        "idempotency_key": item.idempotency_key,
        "status": item.status,
        "created_by": item.created_by,
        "applied_constraint_id": (
            str(item.applied_constraint_id) if item.applied_constraint_id else None
        ),
        "created_at": item.created_at.isoformat(),
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
    }


def _event_payload(item: ProjectEvent, links: list[EventLink] | None = None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "project_id": item.project_id,
        "event_type": item.event_type,
        "title": item.title,
        "content": item.content,
        "occurred_at": item.occurred_at.isoformat(),
        "source": item.source,
        "source_ref": item.source_ref,
        "metadata": item.event_metadata,
        "idempotency_key": item.idempotency_key,
        "created_at": item.created_at.isoformat(),
        "links": [
            {
                "id": str(link.id),
                "target_type": link.target_type,
                "target_id": str(link.target_id),
                "relation": link.relation,
                "metadata": link.link_metadata,
            }
            for link in (links or [])
        ],
    }


def _quality_snapshot_payload(item: ContextQualitySnapshot) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "project_id": item.project_id,
        "dataset_schema_version": item.dataset_schema_version,
        "k": item.k,
        "trigger": item.trigger,
        "dry_run": item.dry_run,
        "passed": item.passed,
        "metrics": item.metrics,
        "thresholds": item.thresholds,
        "idempotency_key": item.idempotency_key,
        "created_at": item.created_at.isoformat(),
    }


def _automation_run_payload(item: AutomationProposalRun) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "project_id": item.project_id,
        "dry_run": item.dry_run,
        "status": item.status,
        "gate": item.gate,
        "plans": item.plans,
        "generated_proposal_ids": item.generated_proposal_ids,
        "idempotency_key": item.idempotency_key,
        "apply_performed": False,
        "created_at": item.created_at.isoformat(),
    }


def _tokens(text: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{1,}", text)}
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        tokens.add(chunk)
        for width in (2, 3, 4):
            tokens.update(chunk[index : index + width] for index in range(len(chunk) - width + 1))
    return tokens


def _constraint_score(constraint: ProjectConstraint, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    title_tokens = _tokens(constraint.title)
    body_tokens = _tokens(constraint.statement + " " + " ".join(constraint.tags or []))
    return 3 * len(query_tokens & title_tokens) + len(query_tokens & body_tokens)


async def _create_artifact_chunks(
    session: AsyncSession,
    artifact: ProjectArtifact,
    *,
    include_embeddings: bool = True,
    require_embeddings: bool = False,
) -> list[ArtifactChunk]:
    raw_chunks = split_artifact_content(artifact.content)
    embeddings: list[list[float] | None] = [None] * len(raw_chunks)
    if include_embeddings and raw_chunks:
        for start in range(0, len(raw_chunks), 8):
            batch = raw_chunks[start : start + 8]
            generated = await get_embeddings(
                [item["content"] for item in batch],
                timeout_seconds=120.0 if require_embeddings else 30.0,
            )
            if generated is None or len(generated) != len(batch):
                if require_embeddings:
                    raise HTTPException(
                        status_code=503,
                        detail="Embedding service did not return every artifact chunk embedding",
                    )
                continue
            embeddings[start : start + len(batch)] = generated
    chunks: list[ArtifactChunk] = []
    for ordinal, item in enumerate(raw_chunks):
        content = item["content"]
        chunk = ArtifactChunk(
            user_id=artifact.user_id,
            project_id=artifact.project_id,
            artifact_id=artifact.id,
            ordinal=ordinal,
            locator=item["locator"],
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            token_count=count_tokens(content),
            embedding=embeddings[ordinal],
        )
        session.add(chunk)
        chunks.append(chunk)
    if chunks:
        await session.flush()
    return chunks


async def _mark_derivations_stale(
    session: AsyncSession,
    previous: ProjectArtifact,
    current: ProjectArtifact,
) -> None:
    now = datetime.now(timezone.utc)
    view_result = await session.execute(
        select(KnowledgeView).where(
            KnowledgeView.user_id == previous.user_id,
            KnowledgeView.project_id == previous.project_id,
            KnowledgeView.status == "current",
        )
    )
    for view in view_result.scalars().all():
        if str(previous.id) in set(view.source_watermark.get("artifact_ids", [])):
            view.status = "stale"
            view.stale_at = now

    evidence_result = await session.execute(
        select(ConstraintEvidence, ProjectConstraint)
        .join(ProjectConstraint, ProjectConstraint.id == ConstraintEvidence.constraint_id)
        .where(
            ConstraintEvidence.user_id == previous.user_id,
            ConstraintEvidence.artifact_id == previous.id,
            ProjectConstraint.status.in_(ACTIVE_CONSTRAINT_STATUSES),
        )
    )
    for evidence, constraint in evidence_result:
        idempotency_key = f"artifact:{current.id}:constraint:{constraint.id}"
        statement = (
            pg_insert(ConstraintRevalidationProposal)
            .values(
                id=uuid.uuid4(),
                user_id=previous.user_id,
                project_id=previous.project_id,
                constraint_id=constraint.id,
                base_version=constraint.version,
                reason=f"Evidence artifact {previous.logical_path} has a newer revision.",
                proposal={"action": "revalidate", "changes": {}},
                source_refs=[
                    {
                        "evidence_id": str(evidence.id),
                        "previous_artifact_id": str(previous.id),
                        "current_artifact_id": str(current.id),
                        "logical_path": previous.logical_path,
                    }
                ],
                idempotency_key=idempotency_key,
                status="pending",
                created_by="system",
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "project_id", "idempotency_key"])
        )
        await session.execute(statement)


async def _create_constraint_revision(
    session: AsyncSession,
    constraint: ProjectConstraint,
    changes: dict[str, Any],
    user_id: str,
) -> ProjectConstraint:
    revision = ProjectConstraint(
        user_id=user_id,
        project_id=constraint.project_id,
        title=changes.get("title", constraint.title),
        statement=changes.get("statement", constraint.statement),
        rationale=changes.get("rationale", constraint.rationale),
        kind=changes.get("kind", constraint.kind),
        status=changes.get("status", constraint.status),
        stability=changes.get("stability", constraint.stability),
        confidence=changes.get("confidence", constraint.confidence),
        source=constraint.source,
        tags=changes.get("tags", constraint.tags),
        version=constraint.version + 1,
        previous_version_id=constraint.id,
        valid_from=changes.get("valid_from", constraint.valid_from),
        valid_to=changes.get("valid_to", constraint.valid_to),
        last_verified_at=changes.get("last_verified_at", constraint.last_verified_at),
        embedding=(
            constraint.embedding
            if "title" not in changes and "statement" not in changes
            else await get_embedding(
                f"{changes.get('title', constraint.title)}\n"
                f"{changes.get('statement', constraint.statement)}"
            )
        ),
    )
    session.add(revision)
    await session.flush()
    evidence_result = await session.execute(
        select(ConstraintEvidence).where(
            ConstraintEvidence.user_id == user_id,
            ConstraintEvidence.constraint_id == constraint.id,
        )
    )
    for evidence in evidence_result.scalars().all():
        session.add(
            ConstraintEvidence(
                user_id=user_id,
                project_id=constraint.project_id,
                constraint_id=revision.id,
                artifact_id=evidence.artifact_id,
                relation=evidence.relation,
                locator=evidence.locator,
                excerpt=evidence.excerpt,
                created_by=evidence.created_by,
                observed_at=evidence.observed_at,
                valid_from=evidence.valid_from,
                valid_to=evidence.valid_to,
                invalidated_at=evidence.invalidated_at,
                source_metadata=evidence.source_metadata,
            )
        )
    edge_result = await session.execute(
        select(ConstraintEdge).where(
            ConstraintEdge.user_id == user_id,
            ConstraintEdge.project_id == constraint.project_id,
            (
                (ConstraintEdge.source_constraint_id == constraint.id)
                | (ConstraintEdge.target_constraint_id == constraint.id)
            ),
        )
    )
    for edge in edge_result.scalars().all():
        session.add(
            ConstraintEdge(
                user_id=user_id,
                project_id=constraint.project_id,
                source_constraint_id=(
                    revision.id
                    if edge.source_constraint_id == constraint.id
                    else edge.source_constraint_id
                ),
                target_constraint_id=(
                    revision.id
                    if edge.target_constraint_id == constraint.id
                    else edge.target_constraint_id
                ),
                relation=edge.relation,
                reason=edge.reason,
                created_by=edge.created_by,
                observed_at=edge.observed_at,
                valid_from=edge.valid_from,
                valid_to=edge.valid_to,
                invalidated_at=edge.invalidated_at,
                source_metadata=edge.source_metadata,
            )
        )
    constraint.status = "superseded"
    constraint.superseded_by = revision.id
    constraint.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return revision


async def _validate_source_refs(
    session: AsyncSession,
    source_refs: list[dict[str, Any]],
    project_id: str,
    user_id: str,
) -> None:
    checks: list[tuple[type, str, uuid.UUID]] = []
    key_models = {
        "artifact_id": ProjectArtifact,
        "previous_artifact_id": ProjectArtifact,
        "current_artifact_id": ProjectArtifact,
        "evidence_id": ConstraintEvidence,
        "constraint_id": ProjectConstraint,
        "memory_id": Memory,
        "event_id": ProjectEvent,
    }
    for ref in source_refs:
        for key, model in key_models.items():
            if ref.get(key):
                try:
                    checks.append((model, key, uuid.UUID(str(ref[key]))))
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422, detail=f"Invalid source ref {key}"
                    ) from exc
    for model, key, item_id in checks:
        filters = [model.id == item_id, model.user_id == user_id]
        if model is not Memory:
            filters.append(model.project_id == project_id)
        item = await session.scalar(select(model.id).where(*filters))
        if item is None:
            raise HTTPException(status_code=422, detail=f"Source ref {key} is outside the project")


async def _validate_event_links(
    session: AsyncSession,
    links: list[Any],
    project_id: str,
    user_id: str,
) -> None:
    model_by_type = {
        "memory": Memory,
        "constraint": ProjectConstraint,
        "artifact": ProjectArtifact,
        "event": ProjectEvent,
    }
    for link in links:
        model = model_by_type[link.target_type]
        filters = [model.id == link.target_id, model.user_id == user_id]
        if model is Memory:
            filters.append(
                (Memory.scope_global.is_(True)) | (Memory.scope_projects.contains([project_id]))
            )
        else:
            filters.append(model.project_id == project_id)
        if await session.scalar(select(model.id).where(*filters)) is None:
            raise HTTPException(
                status_code=422,
                detail=f"Linked {link.target_type} must belong to the project",
            )


@router.get("/workspace")
async def get_workspace(
    project_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    constraint_counts = await session.execute(
        select(ProjectConstraint.status, func.count(ProjectConstraint.id))
        .where(ProjectConstraint.user_id == user_id, ProjectConstraint.project_id == project_id)
        .group_by(ProjectConstraint.status)
    )
    artifact_counts = await session.execute(
        select(ProjectArtifact.kind, func.count(ProjectArtifact.id))
        .where(
            ProjectArtifact.user_id == user_id,
            ProjectArtifact.project_id == project_id,
            ProjectArtifact.status == "current",
        )
        .group_by(ProjectArtifact.kind)
    )
    edge_count = await session.scalar(
        select(func.count(ConstraintEdge.id)).where(
            ConstraintEdge.user_id == user_id, ConstraintEdge.project_id == project_id
        )
    )
    evidence_count = await session.scalar(
        select(func.count(ConstraintEvidence.id)).where(
            ConstraintEvidence.user_id == user_id, ConstraintEvidence.project_id == project_id
        )
    )
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "git_remote": project.git_remote,
            "path_patterns": project.path_patterns,
        },
        "constraint_counts": dict(constraint_counts.all()),
        "artifact_counts": dict(artifact_counts.all()),
        "edge_count": edge_count or 0,
        "evidence_count": evidence_count or 0,
    }


@router.post("/artifacts/sync/check")
async def check_artifact_sync(
    body: ArtifactSyncCheckRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    result = await session.execute(
        select(ProjectArtifact).where(
            ProjectArtifact.user_id == user_id,
            ProjectArtifact.project_id == body.project_id,
            ProjectArtifact.status == "current",
        )
    )
    current = {artifact.logical_path: artifact for artifact in result.scalars().all()}
    incoming = {item.logical_path: item for item in body.artifacts}
    needed = [
        item.logical_path
        for item in body.artifacts
        if item.logical_path not in current
        or current[item.logical_path].content_hash != item.content_hash
    ]
    unchanged = [
        item.logical_path
        for item in body.artifacts
        if item.logical_path in current
        and current[item.logical_path].content_hash == item.content_hash
    ]
    remote_only = sorted(set(current) - set(incoming))
    return {
        "project_id": body.project_id,
        "hash_algorithm": "sha256",
        "needed": needed,
        "unchanged": unchanged,
        "remote_only": remote_only,
        "upload_count": len(needed),
        "saved_bytes": sum(incoming[path].size_bytes for path in unchanged),
    }


@router.post("/artifacts/sync/apply", status_code=status.HTTP_201_CREATED)
async def apply_artifact_sync(
    body: ArtifactSyncApplyRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    created: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for item in body.artifacts:
        actual_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        if actual_hash != item.content_hash:
            raise HTTPException(
                status_code=422,
                detail=f"Content hash mismatch for {item.logical_path}",
            )
        lock_key = f"{user_id}:{body.project_id}:{item.logical_path}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        result = await session.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.user_id == user_id,
                ProjectArtifact.project_id == body.project_id,
                ProjectArtifact.logical_path == item.logical_path,
                ProjectArtifact.status == "current",
            )
            .order_by(ProjectArtifact.revision.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        if previous and previous.content_hash == item.content_hash:
            unchanged.append(item.logical_path)
            continue
        revision = (previous.revision + 1) if previous else 1
        if previous:
            previous.status = "stale"
        artifact = ProjectArtifact(
            user_id=user_id,
            project_id=body.project_id,
            logical_path=item.logical_path,
            kind=item.kind,
            title=item.title,
            content=item.content,
            content_hash=item.content_hash,
            hash_algorithm="sha256",
            size_bytes=item.size_bytes,
            revision=revision,
            source_uri=item.source_uri,
            artifact_metadata=item.metadata,
            supersedes_id=previous.id if previous else None,
        )
        session.add(artifact)
        await session.flush()
        await _create_artifact_chunks(session, artifact)
        if previous:
            await _mark_derivations_stale(session, previous, artifact)
        created.append(_artifact_payload(artifact))
    return {"created": created, "unchanged": unchanged}


@router.get("/artifacts")
async def list_artifacts(
    project_id: str = Query(...),
    status_filter: str = Query("current", alias="status"),
    include_content: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    query = select(ProjectArtifact).where(
        ProjectArtifact.user_id == user_id,
        ProjectArtifact.project_id == project_id,
    )
    if status_filter != "all":
        query = query.where(ProjectArtifact.status == status_filter)
    result = await session.execute(query.order_by(ProjectArtifact.logical_path).limit(limit))
    items = list(result.scalars().all())
    return {"total": len(items), "items": [_artifact_payload(x, include_content) for x in items]}


@router.post("/constraints", status_code=status.HTTP_201_CREATED)
async def create_constraint(
    body: ConstraintCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    existing = await session.scalar(
        select(ProjectConstraint).where(
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == body.project_id,
            ProjectConstraint.title == body.title,
            ProjectConstraint.statement == body.statement,
            ProjectConstraint.status.in_(ACTIVE_CONSTRAINT_STATUSES),
        )
    )
    if existing is not None:
        return _constraint_payload(existing)
    constraint = ProjectConstraint(
        user_id=user_id,
        embedding=await get_embedding(f"{body.title}\n{body.statement}"),
        **body.model_dump(),
    )
    session.add(constraint)
    await session.flush()
    return _constraint_payload(constraint)


@router.patch("/constraints/{constraint_id}")
async def patch_constraint(
    constraint_id: uuid.UUID,
    body: ConstraintPatch,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    result = await session.execute(
        select(ProjectConstraint)
        .where(ProjectConstraint.id == constraint_id, ProjectConstraint.user_id == user_id)
        .with_for_update()
    )
    constraint = result.scalar_one_or_none()
    if constraint is None:
        raise HTTPException(status_code=404, detail="Constraint not found")
    changes = body.model_dump(exclude_unset=True)
    expected_version = changes.pop("expected_version", None)
    if expected_version is not None and expected_version != constraint.version:
        raise HTTPException(status_code=409, detail="Constraint version has changed")
    if constraint.status in {"superseded", "deprecated"} and changes:
        raise HTTPException(status_code=409, detail="Inactive constraint versions are immutable")
    if changes.get("superseded_by") is not None:
        raise HTTPException(status_code=422, detail="superseded_by is managed by the server")
    changes.pop("superseded_by", None)
    if CONSTRAINT_REVISION_FIELDS & changes.keys():
        revision = await _create_constraint_revision(session, constraint, changes, user_id)
        return _constraint_payload(revision)

    for field, value in changes.items():
        setattr(constraint, field, value)
    constraint.updated_at = datetime.now(timezone.utc)
    return _constraint_payload(constraint)


@router.get("/constraints")
async def list_constraints(
    project_id: str = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    query_text: str | None = Query(None, alias="query"),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    query = select(ProjectConstraint).where(
        ProjectConstraint.user_id == user_id, ProjectConstraint.project_id == project_id
    )
    if status_filter:
        query = query.where(ProjectConstraint.status == status_filter)
    result = await session.execute(query.order_by(ProjectConstraint.updated_at.desc()).limit(limit))
    items = list(result.scalars().all())
    if query_text:
        tokens = _tokens(query_text)
        items = [item for item in items if _constraint_score(item, tokens) > 0]
    return {"total": len(items), "items": [_constraint_payload(x) for x in items]}


@router.post("/edges", status_code=status.HTTP_201_CREATED)
async def create_constraint_edge(
    body: ConstraintEdgeCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    ids = {body.source_constraint_id, body.target_constraint_id}
    result = await session.execute(
        select(ProjectConstraint.id).where(
            ProjectConstraint.id.in_(ids),
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == body.project_id,
        )
    )
    if set(result.scalars().all()) != ids:
        raise HTTPException(status_code=422, detail="Both constraints must belong to the project")
    statement = (
        pg_insert(ConstraintEdge)
        .values(id=uuid.uuid4(), user_id=user_id, **body.model_dump())
        .on_conflict_do_nothing(
            index_elements=["user_id", "source_constraint_id", "target_constraint_id", "relation"]
        )
        .returning(ConstraintEdge)
    )
    edge = (await session.execute(statement)).scalar_one_or_none()
    if edge is None:
        edge = await session.scalar(
            select(ConstraintEdge).where(
                ConstraintEdge.user_id == user_id,
                ConstraintEdge.source_constraint_id == body.source_constraint_id,
                ConstraintEdge.target_constraint_id == body.target_constraint_id,
                ConstraintEdge.relation == body.relation,
            )
        )
    if edge is None:
        raise HTTPException(status_code=409, detail="Constraint edge could not be created")
    return _edge_payload(edge)


@router.post("/evidence", status_code=status.HTTP_201_CREATED)
async def create_constraint_evidence(
    body: ConstraintEvidenceCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    constraint = await session.scalar(
        select(ProjectConstraint).where(
            ProjectConstraint.id == body.constraint_id,
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == body.project_id,
        )
    )
    artifact = await session.scalar(
        select(ProjectArtifact).where(
            ProjectArtifact.id == body.artifact_id,
            ProjectArtifact.user_id == user_id,
            ProjectArtifact.project_id == body.project_id,
        )
    )
    if constraint is None or artifact is None:
        raise HTTPException(
            status_code=422, detail="Constraint and artifact must belong to project"
        )
    statement = (
        pg_insert(ConstraintEvidence)
        .values(id=uuid.uuid4(), user_id=user_id, **body.model_dump())
        .on_conflict_do_nothing(
            index_elements=["user_id", "constraint_id", "artifact_id", "relation"]
        )
        .returning(ConstraintEvidence)
    )
    evidence = (await session.execute(statement)).scalar_one_or_none()
    if evidence is None:
        evidence = await session.scalar(
            select(ConstraintEvidence).where(
                ConstraintEvidence.user_id == user_id,
                ConstraintEvidence.constraint_id == body.constraint_id,
                ConstraintEvidence.artifact_id == body.artifact_id,
                ConstraintEvidence.relation == body.relation,
            )
        )
    if evidence is None:
        raise HTTPException(status_code=409, detail="Constraint evidence could not be created")
    return _evidence_payload(evidence)


async def _load_graph(
    session: AsyncSession, project_id: str, user_id: str
) -> tuple[
    list[ProjectConstraint], list[ProjectArtifact], list[ConstraintEdge], list[ConstraintEvidence]
]:
    constraint_result = await session.execute(
        select(ProjectConstraint).where(
            ProjectConstraint.user_id == user_id, ProjectConstraint.project_id == project_id
        )
    )
    artifact_result = await session.execute(
        select(ProjectArtifact).where(
            ProjectArtifact.user_id == user_id,
            ProjectArtifact.project_id == project_id,
        )
    )
    edge_result = await session.execute(
        select(ConstraintEdge).where(
            ConstraintEdge.user_id == user_id, ConstraintEdge.project_id == project_id
        )
    )
    evidence_result = await session.execute(
        select(ConstraintEvidence).where(
            ConstraintEvidence.user_id == user_id, ConstraintEvidence.project_id == project_id
        )
    )
    return (
        list(constraint_result.scalars().all()),
        list(artifact_result.scalars().all()),
        list(edge_result.scalars().all()),
        list(evidence_result.scalars().all()),
    )


@router.get("/graph")
async def get_project_graph(
    project_id: str = Query(...),
    include_inactive: bool = Query(False),
    limit: int = Query(1000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    constraints, artifacts, edges, evidence = await _load_graph(session, project_id, user_id)
    if not include_inactive:
        constraints = [item for item in constraints if item.status in ACTIVE_CONSTRAINT_STATUSES]
    constraints = constraints[:limit]
    constraint_ids = {item.id for item in constraints}
    evidence = [
        item
        for item in evidence
        if item.constraint_id in constraint_ids and item.invalidated_at is None
    ]
    artifact_ids = {item.artifact_id for item in evidence}
    artifacts = [item for item in artifacts if item.id in artifact_ids]
    edges = [
        item
        for item in edges
        if item.source_constraint_id in constraint_ids
        and item.target_constraint_id in constraint_ids
        and item.invalidated_at is None
    ]
    return {
        "project_id": project_id,
        "nodes": [{"node_type": "constraint", **_constraint_payload(item)} for item in constraints]
        + [{"node_type": "artifact", **_artifact_payload(item)} for item in artifacts],
        "edges": [{"edge_type": "constraint", **_edge_payload(item)} for item in edges]
        + [{"edge_type": "evidence", **_evidence_payload(item)} for item in evidence],
    }


def _select_impact_ids(
    constraints: list[ProjectConstraint],
    artifacts: list[ProjectArtifact],
    edges: list[ConstraintEdge],
    evidence: list[ConstraintEvidence],
    body: ProjectImpactRequest,
) -> tuple[set[uuid.UUID], dict[uuid.UUID, list[str]]]:
    active_ids = {item.id for item in constraints if item.status in ACTIVE_CONSTRAINT_STATUSES}
    selected = set(body.constraint_ids) & active_ids
    reasons: dict[uuid.UUID, list[str]] = defaultdict(list)
    changed = set(body.changed_paths)
    artifact_ids = {
        item.id
        for item in artifacts
        if item.logical_path in changed or any(item.logical_path.endswith(path) for path in changed)
    }
    for item in evidence:
        if (
            item.artifact_id in artifact_ids
            and item.constraint_id in active_ids
            and item.invalidated_at is None
        ):
            selected.add(item.constraint_id)
            reasons[item.constraint_id].append(f"linked_to_changed_artifact:{item.relation}")
    query_tokens = _tokens(body.task)
    ranked = sorted(
        (
            (_constraint_score(item, query_tokens), item.id)
            for item in constraints
            if item.status in ACTIVE_CONSTRAINT_STATUSES
        ),
        reverse=True,
    )
    max_score = ranked[0][0] if ranked else 0
    minimum_score = max(2.0, max_score * 0.5)
    for score, constraint_id in ranked[: body.limit]:
        if score >= minimum_score:
            selected.add(constraint_id)
            reasons[constraint_id].append(f"task_match:{score:g}")
    adjacency: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    for edge in edges:
        if (
            edge.invalidated_at is not None
            or edge.source_constraint_id not in active_ids
            or edge.target_constraint_id not in active_ids
        ):
            continue
        if edge.relation in {"impacts", "supersedes"}:
            adjacency[edge.source_constraint_id].append((edge.target_constraint_id, edge.relation))
        elif edge.relation in {"depends_on", "refines"}:
            adjacency[edge.target_constraint_id].append((edge.source_constraint_id, edge.relation))
        elif edge.relation == "conflicts_with":
            adjacency[edge.source_constraint_id].append((edge.target_constraint_id, edge.relation))
            adjacency[edge.target_constraint_id].append((edge.source_constraint_id, edge.relation))
    queue = deque((constraint_id, 0) for constraint_id in selected)
    visited = set(selected)
    while queue:
        current, depth = queue.popleft()
        if depth >= body.depth:
            continue
        for neighbor, relation in adjacency[current]:
            if neighbor in visited:
                continue
            visited.add(neighbor)
            selected.add(neighbor)
            reasons[neighbor].append(f"graph:{relation}:depth_{depth + 1}")
            queue.append((neighbor, depth + 1))
    return selected, reasons


@router.post("/impact")
async def analyze_project_impact(
    body: ProjectImpactRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    constraints, artifacts, edges, evidence = await _load_graph(session, body.project_id, user_id)
    selected, reasons = _select_impact_ids(constraints, artifacts, edges, evidence, body)
    selected_constraints = [item for item in constraints if item.id in selected]
    selected_evidence = [item for item in evidence if item.constraint_id in selected]
    artifact_ids = {item.artifact_id for item in selected_evidence}
    selected_artifacts = [item for item in artifacts if item.id in artifact_ids]
    return {
        "project_id": body.project_id,
        "task": body.task,
        "changed_paths": body.changed_paths,
        "constraints": [
            {**_constraint_payload(item), "selection_reasons": reasons.get(item.id, [])}
            for item in selected_constraints
        ],
        "artifacts": [_artifact_payload(item) for item in selected_artifacts],
        "evidence": [_evidence_payload(item) for item in selected_evidence],
        "traversal": {"depth": body.depth, "selected_count": len(selected)},
    }


def _context_shadow_comparison(legacy: dict[str, Any], compiler: dict[str, Any]) -> dict[str, Any]:
    domains: dict[str, Any] = {}
    for key in ("constraints", "memories", "evidence", "artifacts"):
        legacy_ids = [str(item["id"]) for item in legacy.get(key, []) if item.get("id")]
        compiler_ids = [str(item["id"]) for item in compiler.get(key, []) if item.get("id")]
        legacy_set = set(legacy_ids)
        compiler_set = set(compiler_ids)
        union = legacy_set | compiler_set
        domains[key] = {
            "legacy_count": len(legacy_ids),
            "compiler_count": len(compiler_ids),
            "overlap_count": len(legacy_set & compiler_set),
            "jaccard": round(len(legacy_set & compiler_set) / len(union), 4) if union else 1.0,
            "compiler_only_ids": sorted(compiler_set - legacy_set),
            "legacy_only_ids": sorted(legacy_set - compiler_set),
        }
    return {
        "served_by": "legacy",
        "compiler_context_run_id": compiler.get("context_run_id"),
        "compiler_token_used": compiler.get("token_used"),
        "domains": domains,
    }


async def _legacy_project_context(
    session: AsyncSession,
    project: Project,
    body: ProjectContextRequest,
    user_id: str,
) -> dict[str, Any]:
    impact_body = ProjectImpactRequest(**body.model_dump(), depth=1)
    constraints, artifacts, edges, evidence = await _load_graph(session, body.project_id, user_id)
    selected, reasons = _select_impact_ids(constraints, artifacts, edges, evidence, impact_body)
    selected_constraints = [item for item in constraints if item.id in selected][: body.limit]
    selected_ids = {item.id for item in selected_constraints}
    selected_evidence = [item for item in evidence if item.constraint_id in selected_ids]
    artifact_ids = {item.artifact_id for item in selected_evidence}
    selected_artifacts = [item for item in artifacts if item.id in artifact_ids]
    memory_result = await session.execute(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.status.in_(["active", "ai_review"]),
            Memory.scope_projects.contains([body.project_id]),
        )
    )
    memories = list(memory_result.scalars().all())
    query_tokens = _tokens(body.task)
    memories.sort(
        key=lambda item: len(query_tokens & _tokens(item.title + " " + item.content)), reverse=True
    )
    return {
        "project": {"id": project.id, "name": project.name, "description": project.description},
        "task": body.task,
        "constraints": [
            {**_constraint_payload(item), "selection_reasons": reasons.get(item.id, [])}
            for item in selected_constraints
        ],
        "artifacts": [_artifact_payload(item) for item in selected_artifacts],
        "evidence": [_evidence_payload(item) for item in selected_evidence],
        "memories": [
            {
                "id": str(item.id),
                "title": item.title,
                "type": item.type,
                "status": item.status,
                "content": item.content,
            }
            for item in memories[:10]
        ],
        "usage": {
            "constraint_status_note": "proposed and uncertain constraints are context, not confirmed facts",
            "inactive_note": "superseded and deprecated constraints are excluded from active context",
        },
    }


@router.post("/context")
async def get_project_context(
    body: ProjectContextRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    if settings.context_compiler_enabled and not body.shadow:
        return await compile_project_context(session, project, body, user_id)

    legacy = await _legacy_project_context(session, project, body, user_id)
    if not settings.context_compiler_enabled:
        return legacy

    compiler = await compile_project_context(session, project, body, user_id)
    comparison = _context_shadow_comparison(legacy, compiler)
    context_run_id = compiler.get("context_run_id")
    if context_run_id:
        run = await session.get(ContextRun, uuid.UUID(context_run_id))
        if run is not None:
            run.trace = {**run.trace, "shadow_comparison": comparison}
    legacy["shadow"] = comparison
    return legacy


@router.post("/artifacts/chunks/rebuild")
async def rebuild_artifact_chunks(
    body: ArtifactChunkRebuildRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"artifact-chunk-backfill:{user_id}:{body.project_id}"},
    )
    query = select(ProjectArtifact).where(
        ProjectArtifact.user_id == user_id,
        ProjectArtifact.project_id == body.project_id,
        ProjectArtifact.status == "current",
    )
    if body.artifact_ids:
        query = query.where(ProjectArtifact.id.in_(body.artifact_ids))
    elif body.after_path:
        query = query.where(ProjectArtifact.logical_path > body.after_path)
    if body.missing_only and not body.artifact_ids:
        query = query.where(~exists().where(ArtifactChunk.artifact_id == ProjectArtifact.id))
    fetch_limit = body.limit if body.artifact_ids else body.limit + 1
    result = await session.execute(
        query.order_by(ProjectArtifact.logical_path, ProjectArtifact.id).limit(fetch_limit)
    )
    fetched = list(result.scalars().all())
    has_more = not body.artifact_ids and len(fetched) > body.limit
    artifacts = fetched[: body.limit]
    if body.artifact_ids and {item.id for item in artifacts} != set(body.artifact_ids):
        raise HTTPException(
            status_code=422, detail="All artifacts must be current and in the project"
        )
    created = 0
    embedded = 0
    for artifact in artifacts:
        if not body.missing_only:
            await session.execute(
                delete(ArtifactChunk).where(ArtifactChunk.artifact_id == artifact.id)
            )
        chunks = await _create_artifact_chunks(
            session,
            artifact,
            include_embeddings=body.include_embeddings,
            require_embeddings=body.include_embeddings,
        )
        created += len(chunks)
        embedded += sum(item.embedding is not None for item in chunks)
    return {
        "project_id": body.project_id,
        "artifact_count": len(artifacts),
        "chunk_count": created,
        "embedded_count": embedded,
        "next_cursor": artifacts[-1].logical_path if artifacts else body.after_path,
        "has_more": has_more,
        "missing_only": body.missing_only,
        "rebuildable": True,
    }


@router.get("/artifacts/chunks")
async def list_artifact_chunks(
    project_id: str = Query(...),
    artifact_id: uuid.UUID | None = Query(None),
    include_content: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    query = (
        select(ArtifactChunk, ProjectArtifact)
        .join(ProjectArtifact, ProjectArtifact.id == ArtifactChunk.artifact_id)
        .where(ArtifactChunk.user_id == user_id, ArtifactChunk.project_id == project_id)
    )
    if artifact_id:
        query = query.where(ArtifactChunk.artifact_id == artifact_id)
    result = await session.execute(
        query.order_by(ProjectArtifact.logical_path, ArtifactChunk.ordinal)
        .offset(offset)
        .limit(limit)
    )
    items = []
    for chunk, artifact in result:
        payload = _chunk_payload(chunk, artifact)
        if not include_content:
            payload.pop("content", None)
        items.append(payload)
    return {"total": len(items), "items": items}


@router.post("/constraints/embeddings/rebuild")
async def rebuild_constraint_embeddings(
    body: ConstraintEmbeddingRebuildRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    query = select(ProjectConstraint).where(
        ProjectConstraint.user_id == user_id,
        ProjectConstraint.project_id == body.project_id,
        ProjectConstraint.status.in_(ACTIVE_CONSTRAINT_STATUSES),
    )
    if body.constraint_ids:
        query = query.where(ProjectConstraint.id.in_(body.constraint_ids))
    result = await session.execute(query.limit(body.limit))
    constraints = list(result.scalars().all())
    if body.constraint_ids and {item.id for item in constraints} != set(body.constraint_ids):
        raise HTTPException(
            status_code=422, detail="All constraints must be active and in the project"
        )
    generated = await get_embeddings([constraint_document(item) for item in constraints])
    if generated is None and constraints:
        raise HTTPException(status_code=503, detail="Embedding service is unavailable")
    for item, embedding in zip(constraints, generated or [], strict=False):
        item.embedding = embedding
    return {
        "project_id": body.project_id,
        "constraint_count": len(constraints),
        "embedded_count": len(generated or []),
        "rebuildable": True,
    }


@router.get("/context-runs")
async def list_context_runs(
    project_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    query = select(ContextRun).where(ContextRun.user_id == user_id)
    if project_id:
        project = await _require_project(session, project_id, user_id)
        query = query.where(ContextRun.project_id == project.id)
    result = await session.execute(query.order_by(ContextRun.created_at.desc()).limit(limit))
    items = [
        {
            "id": str(item.id),
            "project_id": item.project_id,
            "query": item.query,
            "mode": item.mode,
            "changed_paths": item.changed_paths,
            "token_budget": item.token_budget,
            "token_used": item.token_used,
            "candidates": item.candidates,
            "selected": item.selected,
            "trace": item.trace,
            "shadow": item.shadow,
            "status": item.status,
            "request_id": item.request_id,
            "client": item.client,
            "client_version": item.client_version,
            "route": item.route,
            "fallback": item.fallback,
            "error_code": item.error_code,
            "created_at": item.created_at.isoformat(),
        }
        for item in result.scalars().all()
    ]
    return {"total": len(items), "items": items}


@router.post("/views", status_code=status.HTTP_201_CREATED)
async def create_knowledge_view(
    body: KnowledgeViewCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    source_refs: list[dict[str, Any]] = []
    plural_keys = {
        "artifact_ids": "artifact_id",
        "constraint_ids": "constraint_id",
        "memory_ids": "memory_id",
        "event_ids": "event_id",
    }
    for plural, singular in plural_keys.items():
        source_refs.extend({singular: item} for item in body.source_watermark.get(plural, []))
    await _validate_source_refs(session, source_refs, body.project_id, user_id)
    previous = None
    if body.supersedes_id:
        previous = await session.scalar(
            select(KnowledgeView)
            .where(
                KnowledgeView.id == body.supersedes_id,
                KnowledgeView.user_id == user_id,
                KnowledgeView.project_id == body.project_id,
            )
            .with_for_update()
        )
        if previous is None:
            raise HTTPException(status_code=422, detail="Superseded view must belong to project")
        if previous.status != "current":
            raise HTTPException(status_code=409, detail="Only current views can be superseded")
    view = KnowledgeView(
        user_id=user_id,
        project_id=body.project_id,
        kind=body.kind,
        query=body.query,
        content=body.content,
        source_watermark=body.source_watermark,
        refresh_mode=body.refresh_mode,
        token_count=count_tokens(body.content),
        producer=body.producer,
        supersedes_id=body.supersedes_id,
    )
    session.add(view)
    await session.flush()
    if previous:
        previous.status = "superseded"
        previous.stale_at = datetime.now(timezone.utc)
    return _view_payload(view)


@router.get("/views")
async def list_knowledge_views(
    project_id: str = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    query = select(KnowledgeView).where(
        KnowledgeView.user_id == user_id,
        KnowledgeView.project_id == project_id,
    )
    if status_filter:
        query = query.where(KnowledgeView.status == status_filter)
    result = await session.execute(query.order_by(KnowledgeView.created_at.desc()).limit(limit))
    items = [_view_payload(item) for item in result.scalars().all()]
    return {"total": len(items), "items": items}


@router.post("/revalidation-proposals", status_code=status.HTTP_201_CREATED)
async def create_revalidation_proposal(
    body: RevalidationProposalCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    constraint = await session.scalar(
        select(ProjectConstraint).where(
            ProjectConstraint.id == body.constraint_id,
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == body.project_id,
        )
    )
    if constraint is None:
        raise HTTPException(status_code=422, detail="Constraint must belong to project")
    if (
        constraint.status not in ACTIVE_CONSTRAINT_STATUSES
        or constraint.version != body.base_version
    ):
        raise HTTPException(status_code=409, detail="Constraint base version is no longer current")
    await _validate_source_refs(session, body.source_refs, body.project_id, user_id)
    statement = (
        pg_insert(ConstraintRevalidationProposal)
        .values(id=uuid.uuid4(), user_id=user_id, status="pending", **body.model_dump())
        .on_conflict_do_nothing(index_elements=["user_id", "project_id", "idempotency_key"])
        .returning(ConstraintRevalidationProposal)
    )
    proposal = (await session.execute(statement)).scalar_one_or_none()
    if proposal is None:
        proposal = await session.scalar(
            select(ConstraintRevalidationProposal).where(
                ConstraintRevalidationProposal.user_id == user_id,
                ConstraintRevalidationProposal.project_id == body.project_id,
                ConstraintRevalidationProposal.idempotency_key == body.idempotency_key,
            )
        )
    if proposal is None:
        raise HTTPException(status_code=409, detail="Proposal could not be created")
    return _proposal_payload(proposal)


@router.get("/revalidation-proposals")
async def list_revalidation_proposals(
    project_id: str = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    query = select(ConstraintRevalidationProposal).where(
        ConstraintRevalidationProposal.user_id == user_id,
        ConstraintRevalidationProposal.project_id == project_id,
    )
    if status_filter:
        query = query.where(ConstraintRevalidationProposal.status == status_filter)
    result = await session.execute(
        query.order_by(ConstraintRevalidationProposal.created_at.desc()).limit(limit)
    )
    items = [_proposal_payload(item) for item in result.scalars().all()]
    return {"total": len(items), "items": items}


@router.post("/revalidation-proposals/{proposal_id}/apply")
async def apply_revalidation_proposal(
    proposal_id: uuid.UUID,
    body: RevalidationApplyRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    proposal = await session.scalar(
        select(ConstraintRevalidationProposal)
        .where(
            ConstraintRevalidationProposal.id == proposal_id,
            ConstraintRevalidationProposal.user_id == user_id,
        )
        .with_for_update()
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Revalidation proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Proposal is no longer pending")
    if body.expected_base_version != proposal.base_version:
        raise HTTPException(status_code=409, detail="Proposal base version mismatch")
    constraint = await session.scalar(
        select(ProjectConstraint)
        .where(
            ProjectConstraint.id == proposal.constraint_id,
            ProjectConstraint.user_id == user_id,
            ProjectConstraint.project_id == proposal.project_id,
        )
        .with_for_update()
    )
    if (
        constraint is None
        or constraint.status not in ACTIVE_CONSTRAINT_STATUSES
        or constraint.version != proposal.base_version
    ):
        proposal.status = "expired"
        proposal.decided_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=409, detail="Constraint changed after proposal creation")
    changes = body.changes.model_dump(exclude_unset=True)
    changes.pop("expected_version", None)
    changes.pop("superseded_by", None)
    changes.setdefault("last_verified_at", datetime.now(timezone.utc))
    revision = await _create_constraint_revision(session, constraint, changes, user_id)
    proposal.status = "applied"
    proposal.applied_constraint_id = revision.id
    proposal.decided_at = datetime.now(timezone.utc)
    return {"proposal": _proposal_payload(proposal), "constraint": _constraint_payload(revision)}


@router.post("/revalidation-proposals/{proposal_id}/reject")
async def reject_revalidation_proposal(
    proposal_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    proposal = await session.scalar(
        select(ConstraintRevalidationProposal)
        .where(
            ConstraintRevalidationProposal.id == proposal_id,
            ConstraintRevalidationProposal.user_id == user_id,
        )
        .with_for_update()
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Revalidation proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Proposal is no longer pending")
    proposal.status = "rejected"
    proposal.decided_at = datetime.now(timezone.utc)
    return _proposal_payload(proposal)


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def append_project_event(
    body: ProjectEventCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    await _validate_event_links(session, body.links, body.project_id, user_id)
    event_id = uuid.uuid4()
    values = body.model_dump(exclude={"links", "metadata"})
    values["occurred_at"] = body.occurred_at or datetime.now(timezone.utc)
    statement = (
        pg_insert(ProjectEvent)
        .values(
            id=event_id,
            user_id=user_id,
            event_metadata=body.metadata,
            created_at=datetime.now(timezone.utc),
            **values,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "project_id", "idempotency_key"])
        .returning(ProjectEvent)
    )
    event = (await session.execute(statement)).scalar_one_or_none()
    if event is None and body.idempotency_key:
        event = await session.scalar(
            select(ProjectEvent).where(
                ProjectEvent.user_id == user_id,
                ProjectEvent.project_id == body.project_id,
                ProjectEvent.idempotency_key == body.idempotency_key,
            )
        )
    if event is None:
        raise HTTPException(status_code=409, detail="Project event could not be appended")
    for link in body.links:
        await session.execute(
            pg_insert(EventLink)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                project_id=body.project_id,
                event_id=event.id,
                target_type=link.target_type,
                target_id=link.target_id,
                relation=link.relation,
                link_metadata=link.metadata,
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "event_id", "target_type", "target_id", "relation"]
            )
        )
    link_result = await session.execute(select(EventLink).where(EventLink.event_id == event.id))
    return _event_payload(event, list(link_result.scalars().all()))


@router.get("/events")
async def list_project_events(
    project_id: str = Query(...),
    event_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    query = select(ProjectEvent).where(
        ProjectEvent.user_id == user_id,
        ProjectEvent.project_id == project_id,
    )
    if event_type:
        query = query.where(ProjectEvent.event_type == event_type)
    result = await session.execute(query.order_by(ProjectEvent.occurred_at.desc()).limit(limit))
    events = list(result.scalars().all())
    event_ids = [item.id for item in events]
    links_by_event: dict[uuid.UUID, list[EventLink]] = defaultdict(list)
    if event_ids:
        link_result = await session.execute(
            select(EventLink).where(EventLink.event_id.in_(event_ids))
        )
        for link in link_result.scalars().all():
            links_by_event[link.event_id].append(link)
    return {
        "total": len(events),
        "items": [_event_payload(item, links_by_event[item.id]) for item in events],
    }


@router.post("/preflight")
async def project_preflight(
    body: ProjectPreflightRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    event_result = await session.execute(
        select(ProjectEvent)
        .where(ProjectEvent.user_id == user_id, ProjectEvent.project_id == body.project_id)
        .order_by(ProjectEvent.occurred_at.desc())
        .limit(1000)
    )
    task_tokens = _tokens(" ".join([body.task, *body.planned_actions, *body.changed_paths]))
    ranked_events: list[tuple[float, ProjectEvent]] = []
    for event in event_result.scalars().all():
        searchable = (
            f"{event.title} {event.content} {json.dumps(event.event_metadata, ensure_ascii=False)}"
        )
        score = len(task_tokens & _tokens(searchable))
        score += 4 * sum(path in searchable for path in body.changed_paths)
        if score > 0:
            ranked_events.append((float(score), event))
    ranked_events.sort(key=lambda item: (item[0], item[1].occurred_at), reverse=True)
    events = [item for _, item in ranked_events[: body.limit]]
    event_ids = [item.id for item in events]
    links_by_event: dict[uuid.UUID, list[EventLink]] = defaultdict(list)
    if event_ids:
        link_result = await session.execute(
            select(EventLink).where(EventLink.event_id.in_(event_ids))
        )
        for link in link_result.scalars().all():
            links_by_event[link.event_id].append(link)

    warnings = []
    supported_events = []
    unknowns = []
    for event in events:
        links = links_by_event[event.id]
        supported = bool(links or event.source_ref)
        event_evidence = [
            {"type": link.target_type, "id": str(link.target_id)} for link in links
        ] or ([{"source_ref": event.source_ref}] if event.source_ref else [])
        if supported:
            supported_events.append({**_event_payload(event, links), "evidence": event_evidence})
        if event.event_type in {"failure", "attempt", "deploy"} and supported:
            warnings.append(
                {
                    "type": f"historical_{event.event_type}",
                    "message": event.title,
                    "event": _event_payload(event, links),
                    "evidence": event_evidence,
                }
            )
        elif event.event_type in {"failure", "attempt", "deploy"}:
            unknowns.append(f"Event {event.id} matched but has no supporting evidence.")

    context = await compile_project_context(
        session,
        project,
        ProjectContextRequest(
            project_id=body.project_id,
            task=body.task,
            changed_paths=body.changed_paths,
            mode="impact",
            limit=body.limit,
            token_budget=4000,
            record_run=False,
        ),
        user_id,
    )
    requirements = [
        item
        for item in context["constraints"]
        if item["stability"] == "invariant"
        or item["kind"] in {"process", "security", "compatibility"}
    ]
    if not warnings and not requirements:
        unknowns.append("No evidence-backed preflight risk was found.")
    return {
        "project_id": body.project_id,
        "task": body.task,
        "read_only": True,
        "decision": "warn" if warnings else "proceed_with_unknowns" if unknowns else "proceed",
        "warnings": warnings,
        "events": supported_events,
        "requirements": requirements,
        "stale_warnings": context["stale_warnings"],
        "unknowns": unknowns,
        "metrics": {
            "matched_events": len(events),
            "evidence_backed_warnings": len(warnings),
            "unsupported_matches": len(unknowns),
        },
    }


@router.get("/eval/cases")
async def get_context_quality_cases(
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    del user_id
    return load_context_quality_cases()


@router.post("/eval/evaluate")
async def evaluate_context_quality_snapshot(
    body: ContextQualityEvalRequest,
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    del user_id
    return evaluate_context_quality(
        load_context_quality_cases(),
        body.results,
        k=body.k,
    )


@router.post("/eval/scale")
async def evaluate_context_scale(
    body: ScaleReplayEvalRequest,
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    """Evaluate scale-conditioned reliability from replay observations."""
    del user_id
    return evaluate_scale_reliability(
        [item.model_dump() for item in body.observations],
        call_budget=body.call_budget,
        reliability_threshold=body.reliability_threshold,
        degradation_tolerance=body.degradation_tolerance,
    )


async def _collect_context_quality_results(
    session: AsyncSession,
    project: Project,
    user_id: str,
    cases: dict[str, Any],
    k: int,
) -> list[dict[str, Any]]:
    """Run the fixed quality dataset inside the trusted Hub process."""
    results: list[dict[str, Any]] = []
    for case in cases["cases"]:
        started = perf_counter()
        context = await compile_project_context(
            session,
            project,
            ProjectContextRequest(
                project_id=project.id,
                task=case["query"],
                changed_paths=case.get("changed_paths", []),
                mode="impact" if case.get("mode") == "preflight" else case.get("mode", "local"),
                limit=k,
                token_budget=6000,
                as_of=case.get("as_of"),
                record_run=False,
            ),
            user_id,
        )
        preflight = None
        if case.get("mode") == "preflight":
            preflight = await project_preflight(
                body=ProjectPreflightRequest(
                    project_id=project.id,
                    task=case["query"],
                    changed_paths=case.get("changed_paths", []),
                    planned_actions=case.get("planned_actions", []),
                    limit=k,
                ),
                session=session,
                user_id=user_id,
            )
        results.append(
            {
                "case_id": case["id"],
                "context": context,
                "preflight": preflight,
                "latency_ms": (perf_counter() - started) * 1000,
                "token_used": context.get("token_used"),
            }
        )
    return results


@router.post("/eval/snapshots", status_code=status.HTTP_201_CREATED)
async def create_context_quality_snapshot(
    body: ContextQualitySnapshotCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    cases = load_context_quality_cases()
    if body.project_id != cases.get("project_id"):
        raise HTTPException(
            status_code=422,
            detail="The fixed quality dataset does not target this project",
        )
    existing = await session.scalar(
        select(ContextQualitySnapshot).where(
            ContextQualitySnapshot.user_id == user_id,
            ContextQualitySnapshot.project_id == body.project_id,
            ContextQualitySnapshot.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        return _quality_snapshot_payload(existing)
    results = await _collect_context_quality_results(session, project, user_id, cases, body.k)
    report = evaluate_context_quality(cases, results, k=body.k)
    snapshot_id = uuid.uuid4()
    statement = (
        pg_insert(ContextQualitySnapshot)
        .values(
            id=snapshot_id,
            user_id=user_id,
            project_id=body.project_id,
            dataset_schema_version=int(report["schema_version"]),
            k=body.k,
            trigger=body.trigger,
            dry_run=body.dry_run,
            passed=bool(report["passed"]),
            metrics=report["metrics"],
            thresholds=report["thresholds"],
            report=report,
            idempotency_key=body.idempotency_key,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "project_id", "idempotency_key"])
        .returning(ContextQualitySnapshot)
    )
    snapshot = (await session.execute(statement)).scalar_one_or_none()
    if snapshot is None:
        snapshot = await session.scalar(
            select(ContextQualitySnapshot).where(
                ContextQualitySnapshot.user_id == user_id,
                ContextQualitySnapshot.project_id == body.project_id,
                ContextQualitySnapshot.idempotency_key == body.idempotency_key,
            )
        )
    if snapshot is None:
        raise HTTPException(status_code=409, detail="Quality snapshot could not be recorded")
    return _quality_snapshot_payload(snapshot)


@router.get("/eval/snapshots")
async def list_context_quality_snapshots(
    project_id: str = Query(...),
    limit: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    result = await session.execute(
        select(ContextQualitySnapshot)
        .where(
            ContextQualitySnapshot.user_id == user_id,
            ContextQualitySnapshot.project_id == project_id,
        )
        .order_by(ContextQualitySnapshot.created_at.desc())
        .limit(limit)
    )
    items = list(result.scalars().all())
    return {"total": len(items), "items": [_quality_snapshot_payload(item) for item in items]}


async def _quality_gate(
    session: AsyncSession,
    project_id: str,
    user_id: str,
    required_snapshots: int,
) -> dict[str, Any]:
    result = await session.execute(
        select(ContextQualitySnapshot)
        .where(
            ContextQualitySnapshot.user_id == user_id,
            ContextQualitySnapshot.project_id == project_id,
        )
        .order_by(ContextQualitySnapshot.created_at.desc())
        .limit(required_snapshots)
    )
    return evaluate_automation_gate(
        list(result.scalars().all()), required_snapshots=required_snapshots
    )


@router.get("/automation/gate")
async def get_automation_gate(
    project_id: str = Query(...),
    required_snapshots: int = Query(3, ge=2, le=10),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    gate = await _quality_gate(session, project_id, user_id, required_snapshots)
    gate["feature_enabled"] = settings.project_automation_enabled
    gate["proposal_only"] = True
    return gate


@router.post("/automation/proposals/run", status_code=status.HTTP_201_CREATED)
async def run_proposal_automation(
    body: AutomationProposalRunCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, body.project_id, user_id)
    body.project_id = project.id
    existing = await session.scalar(
        select(AutomationProposalRun).where(
            AutomationProposalRun.user_id == user_id,
            AutomationProposalRun.project_id == body.project_id,
            AutomationProposalRun.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        return _automation_run_payload(existing)

    gate = await _quality_gate(session, body.project_id, user_id, body.required_snapshots)
    gate["feature_enabled"] = settings.project_automation_enabled
    gate["proposal_only"] = True
    plans: dict[str, Any] = {"sleep": [], "revalidation": []}

    if body.include_sleep:
        memory_result = await session.execute(
            select(Memory).where(
                Memory.user_id == user_id,
                Memory.status.in_(["active", "ai_review", "pending"]),
                Memory.sleep_state == "fresh",
                Memory.is_core.is_(False),
                Memory.scope_projects.contains([body.project_id]),
            )
        )
        plans["sleep"] = [
            {
                "memory_id": str(item.id),
                "title": item.title,
                "status": item.status,
                "requires_ai_plan": True,
            }
            for item in memory_result.scalars().all()
        ]

    if body.include_revalidation:
        constraint_result = await session.execute(
            select(ProjectConstraint).where(
                ProjectConstraint.user_id == user_id,
                ProjectConstraint.project_id == body.project_id,
                ProjectConstraint.status.in_(ACTIVE_CONSTRAINT_STATUSES),
            )
        )
        active_constraints = {item.id: item for item in constraint_result.scalars().all()}
        evidence_result = await session.execute(
            select(ConstraintEvidence, ProjectArtifact)
            .join(ProjectArtifact, ProjectArtifact.id == ConstraintEvidence.artifact_id)
            .where(
                ConstraintEvidence.user_id == user_id,
                ConstraintEvidence.project_id == body.project_id,
                ConstraintEvidence.constraint_id.in_(active_constraints),
            )
        )
        current_result = await session.execute(
            select(ProjectArtifact).where(
                ProjectArtifact.user_id == user_id,
                ProjectArtifact.project_id == body.project_id,
                ProjectArtifact.status == "current",
            )
        )
        current_by_path = {item.logical_path: item for item in current_result.scalars().all()}
        pending_result = await session.execute(
            select(ConstraintRevalidationProposal.constraint_id).where(
                ConstraintRevalidationProposal.user_id == user_id,
                ConstraintRevalidationProposal.project_id == body.project_id,
                ConstraintRevalidationProposal.status == "pending",
            )
        )
        pending_constraint_ids = set(pending_result.scalars().all())
        stale_refs: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
        for evidence_item, artifact in evidence_result:
            current = current_by_path.get(artifact.logical_path)
            if current is not None and current.id != artifact.id:
                stale_refs[evidence_item.constraint_id].append(
                    {
                        "evidence_id": str(evidence_item.id),
                        "previous_artifact_id": str(artifact.id),
                        "current_artifact_id": str(current.id),
                        "logical_path": artifact.logical_path,
                    }
                )
        for constraint_id, source_refs in stale_refs.items():
            if constraint_id in pending_constraint_ids:
                continue
            constraint = active_constraints[constraint_id]
            plans["revalidation"].append(
                {
                    "constraint_id": str(constraint.id),
                    "base_version": constraint.version,
                    "reason": "Referenced artifact revision changed; revalidate before reuse.",
                    "proposal": {"action": "revalidate", "changes": {}},
                    "source_refs": source_refs,
                    "idempotency_key": f"auto-revalidate-{constraint.id}-v{constraint.version}",
                }
            )

    generated_proposal_ids: list[str] = []
    can_generate = gate["eligible"] and settings.project_automation_enabled
    run_status = "dry_run" if body.dry_run else "generated" if can_generate else "gate_rejected"
    if not body.dry_run and can_generate:
        for plan in plans["revalidation"]:
            proposal_id = uuid.uuid4()
            proposal_result = await session.execute(
                pg_insert(ConstraintRevalidationProposal)
                .values(
                    id=proposal_id,
                    user_id=user_id,
                    project_id=body.project_id,
                    constraint_id=uuid.UUID(plan["constraint_id"]),
                    base_version=plan["base_version"],
                    reason=plan["reason"],
                    proposal=plan["proposal"],
                    source_refs=plan["source_refs"],
                    idempotency_key=plan["idempotency_key"],
                    status="pending",
                    created_by="ai",
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(index_elements=["user_id", "project_id", "idempotency_key"])
                .returning(ConstraintRevalidationProposal.id)
            )
            generated_id = proposal_result.scalar_one_or_none()
            if generated_id is None:
                generated_id = await session.scalar(
                    select(ConstraintRevalidationProposal.id).where(
                        ConstraintRevalidationProposal.user_id == user_id,
                        ConstraintRevalidationProposal.project_id == body.project_id,
                        ConstraintRevalidationProposal.idempotency_key == plan["idempotency_key"],
                    )
                )
            if generated_id is not None:
                generated_proposal_ids.append(str(generated_id))

    run = AutomationProposalRun(
        user_id=user_id,
        project_id=body.project_id,
        dry_run=body.dry_run,
        status=run_status,
        gate=gate,
        plans=plans,
        generated_proposal_ids=generated_proposal_ids,
        idempotency_key=body.idempotency_key,
    )
    session.add(run)
    await session.flush()
    return _automation_run_payload(run)


@router.get("/automation/runs")
async def list_proposal_automation_runs(
    project_id: str = Query(...),
    limit: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    project = await _require_project(session, project_id, user_id)
    project_id = project.id
    result = await session.execute(
        select(AutomationProposalRun)
        .where(
            AutomationProposalRun.user_id == user_id,
            AutomationProposalRun.project_id == project_id,
        )
        .order_by(AutomationProposalRun.created_at.desc())
        .limit(limit)
    )
    items = list(result.scalars().all())
    return {"total": len(items), "items": [_automation_run_payload(item) for item in items]}
