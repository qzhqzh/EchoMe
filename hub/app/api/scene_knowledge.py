"""Source-backed scene documents assembled from independent text entries."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Project
from app.models.scene_knowledge import SceneKnowledge, SceneKnowledgeChange, SceneKnowledgeEntry
from app.schemas.scene_knowledge import (
    SceneEntryBatchCreate,
    SceneEntryCorrection,
    SceneEntryCreate,
    SceneKnowledgeCreate,
    SceneSopPublish,
    SopValidation,
    validate_sop,
)
from app.services.content_safety import require_safe_content

router = APIRouter(prefix="/scenarios/knowledge", tags=["scene-knowledge"])

PREFIX = {"fact": "F", "observation": "O", "sop": "S", "caution": "C", "work": "T"}
ORDER = tuple(PREFIX)
HEADING = {
    "fact": "事实",
    "observation": "历史观测",
    "sop": "已验证 SOP",
    "caution": "注意事项",
    "work": "进行中",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe(value: Any) -> None:
    require_safe_content(json.dumps(value, ensure_ascii=False, default=str))


def _scene_payload(scene: SceneKnowledge) -> dict[str, Any]:
    return {
        "id": str(scene.id),
        "slug": scene.slug,
        "title": scene.title,
        "summary": scene.summary,
        "aliases": scene.aliases,
        "project_id": scene.project_id,
        "status": scene.status,
        "created_at": scene.created_at.isoformat(),
        "updated_at": scene.updated_at.isoformat(),
    }


def _entry_payload(entry: SceneKnowledgeEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "key": f"{PREFIX[entry.category]}{entry.number:03d}",
        "category": entry.category,
        "content": entry.content,
        "source_ref": entry.source_ref,
        "origin_entry_id": str(entry.origin_entry_id) if entry.origin_entry_id else None,
        "evidence_at": entry.evidence_at.isoformat() if entry.evidence_at else None,
        "status": entry.status,
        "validations": entry.validations,
        "revision": entry.revision,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _snapshot(entry: SceneKnowledgeEntry) -> dict[str, Any]:
    return _entry_payload(entry)


def _markdown(scene: SceneKnowledge, entries: list[SceneKnowledgeEntry]) -> str:
    lines = [f"# {scene.title}"]
    if scene.summary:
        lines.extend(["", scene.summary])
    for category in ORDER:
        selected = [entry for entry in entries if entry.category == category]
        lines.extend(
            [
                "",
                f"## {HEADING[category]}（{sum(entry.status == 'active' for entry in selected)} 条）",
            ]
        )
        if not selected:
            lines.append("暂无。")
        for entry in selected:
            key = f"{PREFIX[category]}{entry.number:03d}"
            label = {
                "needs_review": "〔待核实〕",
                "archived": "〔已归档〕",
            }.get(entry.status, "")
            if category == "sop":
                lines.extend(["", f"### {key}{label}", entry.content])
            else:
                content = entry.content.replace("\n", "\n  ")
                lines.append(f"- {key}{label} {content}")
            meta = f"来源：{entry.source_ref}"
            if entry.evidence_at:
                meta += f"；证据时间：{entry.evidence_at.isoformat()}"
            lines.append(f"  - {meta}" if category != "sop" else f"  *{meta}*")
    return "\n".join(lines).strip() + "\n"


async def _lock_selectors(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"scene-knowledge-selectors:{user_id}"},
    )


async def _unique_selector(
    session: AsyncSession, user_id: str, slug: str, aliases: list[str]
) -> None:
    incoming = {slug.casefold(), *(alias.casefold() for alias in aliases)}
    if len(incoming) != len(aliases) + 1:
        raise HTTPException(status_code=409, detail="Scene slug and aliases overlap")
    existing = (
        await session.scalars(select(SceneKnowledge).where(SceneKnowledge.user_id == user_id))
    ).all()
    for scene in existing:
        if incoming & {scene.slug.casefold(), *(alias.casefold() for alias in scene.aliases)}:
            raise HTTPException(status_code=409, detail="Scene selector already exists")


async def _scene(
    session: AsyncSession, selector: str, user_id: str, *, lock: bool = False
) -> SceneKnowledge:
    scenes = (
        await session.scalars(select(SceneKnowledge).where(SceneKnowledge.user_id == user_id))
    ).all()
    key = selector.strip().casefold()
    found = next(
        (
            scene
            for scene in scenes
            if scene.slug.casefold() == key or key in {alias.casefold() for alias in scene.aliases}
        ),
        None,
    )
    if found is None:
        raise HTTPException(status_code=404, detail="Scene knowledge not found")
    if lock:
        found = await session.scalar(
            select(SceneKnowledge).where(SceneKnowledge.id == found.id).with_for_update()
        )
        assert found is not None
    return found


async def _entry(
    session: AsyncSession,
    scene: SceneKnowledge,
    entry_id: uuid.UUID,
    user_id: str,
    *,
    lock: bool = False,
) -> SceneKnowledgeEntry:
    query = select(SceneKnowledgeEntry).where(
        SceneKnowledgeEntry.id == entry_id,
        SceneKnowledgeEntry.scene_id == scene.id,
        SceneKnowledgeEntry.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    entry = await session.scalar(query)
    if entry is None:
        raise HTTPException(status_code=404, detail="Scene entry not found")
    return entry


async def _reject_duplicate(
    session: AsyncSession,
    scene: SceneKnowledge,
    category: str,
    content: str,
    except_id: uuid.UUID | None = None,
) -> None:
    entries = (
        await session.scalars(
            select(SceneKnowledgeEntry).where(
                SceneKnowledgeEntry.scene_id == scene.id,
                SceneKnowledgeEntry.category == category,
                SceneKnowledgeEntry.status != "archived",
            )
        )
    ).all()
    normalized = content.strip().casefold()
    if any(
        entry.id != except_id and entry.content.strip().casefold() == normalized
        for entry in entries
    ):
        raise HTTPException(status_code=409, detail="Identical active scene entry already exists")


async def _add(
    session: AsyncSession,
    scene: SceneKnowledge,
    user_id: str,
    *,
    category: str,
    content: str,
    source_ref: str,
    evidence_at: datetime | None,
    status: str = "active",
    validations: list[dict[str, Any]] | None = None,
    origin_entry_id: uuid.UUID | None = None,
) -> SceneKnowledgeEntry:
    if scene.status != "active":
        raise HTTPException(status_code=409, detail="Scene knowledge is archived")
    await _reject_duplicate(session, scene, category, content)
    number = await session.scalar(
        select(func.max(SceneKnowledgeEntry.number)).where(
            SceneKnowledgeEntry.scene_id == scene.id,
            SceneKnowledgeEntry.category == category,
        )
    )
    entry = SceneKnowledgeEntry(
        user_id=user_id,
        scene_id=scene.id,
        category=category,
        number=(number or 0) + 1,
        content=content.strip(),
        source_ref=source_ref.strip(),
        origin_entry_id=origin_entry_id,
        evidence_at=evidence_at,
        status=status,
        validations=validations or [],
        revision=1,
    )
    session.add(entry)
    await session.flush()
    session.add(
        SceneKnowledgeChange(
            user_id=user_id,
            entry_id=entry.id,
            revision=1,
            action="add",
            reason="Initial entry",
            snapshot=_snapshot(entry),
        )
    )
    scene.updated_at = _now()
    return entry


@router.post("", status_code=201)
async def create_scene_knowledge(
    body: SceneKnowledgeCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe(body.model_dump())
    await _lock_selectors(session, user_id)
    await _unique_selector(session, user_id, body.slug, body.aliases)
    if (
        body.project_id
        and await session.scalar(
            select(Project.id).where(
                Project.id == body.project_id,
                Project.user_id == user_id,
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    scene = SceneKnowledge(user_id=user_id, **body.model_dump())
    session.add(scene)
    await session.flush()
    return {"scene": _scene_payload(scene)}


@router.get("")
async def list_scene_knowledge(
    query: str | None = Query(None, max_length=256),
    project_id: str | None = None,
    include_archived: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    scenes = (
        await session.scalars(
            select(SceneKnowledge)
            .where(SceneKnowledge.user_id == user_id)
            .order_by(SceneKnowledge.updated_at.desc())
        )
    ).all()
    if not include_archived:
        scenes = [scene for scene in scenes if scene.status == "active"]
    if project_id is not None:
        scenes = [scene for scene in scenes if scene.project_id == project_id]
    if query:
        needle = query.strip().casefold()
        scenes = [
            scene
            for scene in scenes
            if needle
            in " ".join(
                [
                    scene.slug,
                    scene.title,
                    scene.summary,
                    *scene.aliases,
                ]
            ).casefold()
        ]
    return {
        "total": len(scenes),
        "items": [_scene_payload(scene) for scene in scenes[offset : offset + limit]],
    }


@router.get("/{selector}")
async def get_scene_knowledge(
    selector: str,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    scene = await _scene(session, selector, user_id)
    entries = (
        await session.scalars(
            select(SceneKnowledgeEntry)
            .where(
                SceneKnowledgeEntry.scene_id == scene.id,
                SceneKnowledgeEntry.user_id == user_id,
            )
            .order_by(SceneKnowledgeEntry.number)
        )
    ).all()
    entries = sorted(entries, key=lambda entry: (ORDER.index(entry.category), entry.number))
    visible = (
        entries if include_archived else [entry for entry in entries if entry.status != "archived"]
    )
    counts = {
        category: sum(entry.category == category and entry.status == "active" for entry in visible)
        for category in ORDER
    }
    return {
        "scene": _scene_payload(scene),
        "counts": counts,
        "entries": [_entry_payload(entry) for entry in visible],
        "markdown": _markdown(scene, visible),
    }


@router.post("/{selector}/entries", status_code=201)
async def add_scene_entry(
    selector: str,
    body: SceneEntryCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe(body.model_dump())
    scene = await _scene(session, selector, user_id, lock=True)
    entry = await _add(session, scene, user_id, **body.model_dump())
    return {"entry": _entry_payload(entry)}


@router.post("/{selector}/entries/batch", status_code=201)
async def add_scene_entries_batch(
    selector: str,
    body: SceneEntryBatchCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe(body.model_dump())
    scene = await _scene(session, selector, user_id, lock=True)
    entries = [await _add(session, scene, user_id, **item.model_dump()) for item in body.entries]
    return {"entries": [_entry_payload(entry) for entry in entries]}


@router.post("/{selector}/sops", status_code=201)
async def publish_scene_sop(
    selector: str,
    body: SceneSopPublish,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe(body.model_dump())
    scene = await _scene(session, selector, user_id, lock=True)
    if body.candidate_entry_id is not None:
        candidate = await _entry(session, scene, body.candidate_entry_id, user_id)
        if candidate.category != "work":
            raise HTTPException(status_code=422, detail="SOP candidate must be a work entry")
    entry = await _add(
        session,
        scene,
        user_id,
        category="sop",
        content=body.content,
        source_ref=body.source_ref,
        evidence_at=None,
        validations=[item.model_dump(mode="json") for item in body.validations],
        origin_entry_id=body.candidate_entry_id,
    )
    return {"entry": _entry_payload(entry)}


@router.patch("/{selector}/entries/{entry_id}")
async def correct_scene_entry(
    selector: str,
    entry_id: uuid.UUID,
    body: SceneEntryCorrection,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe(body.model_dump())
    scene = await _scene(session, selector, user_id)
    if scene.status != "active":
        raise HTTPException(status_code=409, detail="Scene knowledge is archived")
    entry = await _entry(session, scene, entry_id, user_id, lock=True)
    if body.expected_revision != entry.revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Scene entry changed; read current revision before correcting",
                "current_revision": entry.revision,
            },
        )
    if entry.status == "archived" and body.status != "active":
        raise HTTPException(status_code=409, detail="Archived entry cannot be changed")
    new_content = body.content.strip() if body.content is not None else entry.content
    if not new_content:
        raise HTTPException(status_code=422, detail="Entry content cannot be empty")
    if entry.category in {"fact", "observation", "caution"} and (
        "\n" in new_content or len(new_content) > 1000
    ):
        raise HTTPException(
            status_code=422, detail="Keep each fact, observation, or caution atomic"
        )
    if (
        body.content is not None
        and entry.category in {"fact", "observation"}
        and body.evidence_at is None
    ):
        raise HTTPException(
            status_code=422, detail="Corrected facts and observations need evidence_at"
        )
    sop_revalidation = entry.category == "sop" and (
        body.content is not None or (body.status == "active" and entry.status != "active")
    )
    if sop_revalidation:
        if body.validations is None:
            raise HTTPException(
                status_code=422, detail="Changed or reactivated SOP needs fresh validation evidence"
            )
        try:
            validate_sop(new_content, body.validations)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        old_refs = {item.get("evidence_ref") for item in entry.validations}
        new_refs = {item.evidence_ref for item in body.validations}
        if old_refs & new_refs:
            raise HTTPException(
                status_code=422, detail="SOP revalidation needs new evidence references"
            )
        entry.validations = [item.model_dump(mode="json") for item in body.validations]
    elif body.validations is not None:
        raise HTTPException(status_code=422, detail="Validations apply only to changed SOP content")
    await _reject_duplicate(session, scene, entry.category, new_content, except_id=entry.id)
    changed = (
        new_content != entry.content
        or body.status not in {None, entry.status}
        or body.evidence_at not in {None, entry.evidence_at}
    )
    if not changed:
        raise HTTPException(status_code=422, detail="Correction did not change the entry")
    entry.content = new_content
    entry.source_ref = body.source_ref.strip()
    if body.evidence_at is not None:
        entry.evidence_at = body.evidence_at
    if body.status is not None:
        entry.status = body.status
    entry.revision += 1
    entry.updated_at = _now()
    scene.updated_at = _now()
    session.add(
        SceneKnowledgeChange(
            user_id=user_id,
            entry_id=entry.id,
            revision=entry.revision,
            action="correct" if body.content is not None else "status",
            reason=body.reason.strip(),
            snapshot=_snapshot(entry),
        )
    )
    await session.flush()
    return {"entry": _entry_payload(entry)}


@router.get("/{selector}/entries/{entry_id}/history")
async def scene_entry_history(
    selector: str,
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    scene = await _scene(session, selector, user_id)
    await _entry(session, scene, entry_id, user_id)
    changes = (
        await session.scalars(
            select(SceneKnowledgeChange)
            .where(
                SceneKnowledgeChange.entry_id == entry_id,
                SceneKnowledgeChange.user_id == user_id,
            )
            .order_by(SceneKnowledgeChange.revision)
        )
    ).all()
    return {
        "items": [
            {
                "revision": change.revision,
                "action": change.action,
                "reason": change.reason,
                "snapshot": change.snapshot,
                "created_at": change.created_at.isoformat(),
            }
            for change in changes
        ]
    }
