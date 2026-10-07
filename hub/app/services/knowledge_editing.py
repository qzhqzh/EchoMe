"""Atomic entry creation and bounded reference choices for human editing."""

from typing import Any, get_args
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.knowledge import KnowledgeRecord
from app.schemas.knowledge import Kind, KnowledgeCapture, RecordCreate, RecordUpdate
from app.services.knowledge import (
    INACTIVE,
    Principal,
    create_record,
    expand,
    get_record,
    lock_writes,
    update_record,
)
from app.services.knowledge_navigation import node, page, placement_paths


async def capture_entry(
    session: AsyncSession, principal: Principal, body: KnowledgeCapture
) -> dict[str, Any]:
    kind = body.record.kind
    if kind not in ("project", "question", "entity"):
        raise HTTPException(422, "Capture supports projects, questions and knowledge")
    if (body.placement or body.context_id) and kind != "entity":
        raise HTTPException(422, "Only knowledge can be classified or referenced")
    if body.first_question and kind != "project":
        raise HTTPException(422, "An initial question requires a project")
    root = await create_record(session, principal, body.record)
    created: dict[str, str] = {}
    records: list[tuple[str, dict[str, Any]]] = []
    if body.placement is not None:
        records.append(
            (
                "placement",
                {
                    "entity_id": str(root.id),
                    "parent_id": str(body.placement.parent_id)
                    if body.placement.parent_id
                    else None,
                },
            )
        )
    if body.context_id:
        records.append(
            (
                "usage",
                {
                    "context_id": str(body.context_id),
                    "knowledge_id": str(root.id),
                    "knowledge_revision": root.revision,
                    "role": "to_research",
                },
            )
        )
    if body.first_question:
        records.append(("question", {"title": body.first_question, "project_id": str(root.id)}))
    for child_kind, data in records:
        child = await create_record(
            session, principal, RecordCreate.model_validate({"kind": child_kind, "data": data})
        )
        created[child_kind + "_id"] = str(child.id)
    # The request transaction commits only after every related write has succeeded.
    return {"record": await expand(session, root), "created": created}


async def remove_placement(
    session: AsyncSession, principal: Principal, placement_id: UUID, expected_revision: int
) -> dict[str, Any]:
    # Share the write lock with moves and new children; a browser preflight alone races.
    await lock_writes(session, principal.user_id)
    row = await get_record(session, principal.user_id, placement_id)
    if row.kind != "placement":
        raise HTTPException(422, "Only a directory position can be removed")
    children = await session.scalar(
        select(KnowledgeRecord.id)
        .where(
            KnowledgeRecord.user_id == principal.user_id,
            KnowledgeRecord.kind == "placement",
            KnowledgeRecord.status.not_in(INACTIVE),
            KnowledgeRecord.payload["parent_id"].astext == str(row.id),
        )
        .limit(1)
    )
    if children:
        raise HTTPException(409, "Directory position has active children")
    updated = await update_record(
        session,
        principal,
        row.id,
        RecordUpdate(
            expected_revision=expected_revision,
            data={**row.payload, "status": "archived"},
            reason="Remove a leaf classification; preserve knowledge and history",
        ),
    )
    return await expand(session, updated)


async def reference_choices(
    session: AsyncSession,
    principal: Principal,
    kinds: str,
    search: str | None,
    exclude_id: UUID | None,
    exclude_topics: bool,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    selected = list(dict.fromkeys(kinds.split(",")))
    if not selected or len(selected) > 4 or set(selected) - set(get_args(Kind)):
        raise HTTPException(422, "Unknown reference kinds")
    record = KnowledgeRecord
    if "placement" in selected:
        if selected != ["placement"]:
            raise HTTPException(422, "Directory positions are a separate choice list")
        entity = aliased(record)
        query = (
            select(record, entity)
            .join(entity, record.payload["entity_id"].astext == entity.id.cast(Text))
            .where(
                record.user_id == principal.user_id,
                record.kind == "placement",
                record.status.not_in(INACTIVE),
                entity.user_id == principal.user_id,
                entity.kind == "entity",
                entity.status.not_in(INACTIVE),
            )
        )
        title = entity.payload["name"].astext
        if exclude_id:
            query = query.where(entity.id != exclude_id, record.id != exclude_id)
    else:
        query = select(record, record).where(
            record.user_id == principal.user_id,
            record.kind.in_(selected),
            record.status.not_in(INACTIVE),
        )
        title = func.coalesce(
            record.payload["name"].astext,
            record.payload["title"].astext,
            record.payload["label"].astext,
            record.payload["statement_md"].astext,
            "",
        )
        if exclude_id:
            query = query.where(record.id != exclude_id)
        if exclude_topics:
            query = query.where(
                or_(record.kind != "entity", record.payload["entity_kind"].astext != "topic")
            )
    if search and search.strip():
        text = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(title.ilike("%" + text + "%", escape="\\"))
    total = (await session.scalar(select(func.count()).select_from(query.subquery()))) or 0
    rows = (
        await session.execute(query.order_by(title, record.id).offset(offset).limit(limit))
    ).all()
    items = [{**node(target), "id": str(row.id), "kind": row.kind} for row, target in rows]
    if selected == ["placement"]:
        paths = await placement_paths(session, principal, [row for row, _ in rows])
        for item, path in zip(items, paths, strict=True):
            item["path"] = path
    return page(items, total, offset)
