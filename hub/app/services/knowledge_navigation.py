"""Paged project navigation and explicit paths back from shared knowledge."""

from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Text, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.knowledge import KnowledgeRecord
from app.services.knowledge import INACTIVE, Principal, get_record


def node(row: KnowledgeRecord) -> dict[str, Any]:
    data = row.payload
    return {
        "id": str(row.id),
        "kind": row.kind,
        "name": data.get("name") or data.get("title") or data.get("statement_md") or row.kind,
        "summary": data.get("summary", ""),
        "status": row.status,
        "entity_kind": data.get("entity_kind"),
        "revision": row.revision,
        "child_count": 0,
    }


def page(items: list[dict[str, Any]], total: int, offset: int) -> dict[str, Any]:
    following = offset + len(items)
    return {"items": items, "total": total, "next_offset": following if following < total else None}


async def project_tree(
    session: AsyncSession,
    principal: Principal,
    *,
    parent_id: UUID | None = None,
    independent: bool = False,
    offset: int = 0,
    limit: int = 30,
) -> dict[str, Any]:
    if parent_id and independent:
        raise HTTPException(422, "Choose a parent or independent questions")
    record = KnowledgeRecord
    owned = [record.user_id == principal.user_id, record.status.not_in(INACTIVE)]
    independent_query = select(record).where(
        *owned, record.kind == "question", record.payload["project_id"].astext.is_(None)
    )
    independent_total = 0
    if parent_id:
        parent = await get_record(session, principal.user_id, parent_id)
        if parent.kind not in ("project", "question"):
            raise HTTPException(422, "Only projects and questions have a project branch")
        clauses = [
            and_(record.kind == "usage", record.payload["context_id"].astext == str(parent_id))
        ]
        if parent.kind == "project":
            clauses.append(
                and_(
                    record.kind == "question", record.payload["project_id"].astext == str(parent_id)
                )
            )
        query = select(record).where(*owned, or_(*clauses))
    else:
        independent_total = (
            await session.scalar(select(func.count()).select_from(independent_query.subquery()))
        ) or 0
        query = (
            independent_query
            if independent
            else select(record).where(*owned, record.kind == "project")
        )
    total = (await session.scalar(select(func.count()).select_from(query.subquery()))) or 0
    rows = list(
        await session.scalars(
            query.order_by(case((record.kind == "usage", 1), else_=0), record.created_at, record.id)
            .offset(offset)
            .limit(limit)
        )
    )
    target_ids = [row.payload["knowledge_id"] for row in rows if row.kind == "usage"]
    targets = (
        {
            str(row.id): row
            for row in await session.scalars(
                select(record).where(record.user_id == principal.user_id, record.id.in_(target_ids))
            )
        }
        if target_ids
        else {}
    )
    items = []
    for row in rows:
        if row.kind == "usage":
            target = targets[row.payload["knowledge_id"]]
            item = node(target)
            item.update(
                {
                    "via_id": str(row.id),
                    "role": row.payload["role"],
                    "knowledge_revision": row.payload["knowledge_revision"],
                }
            )
        else:
            item = node(row)
        items.append(item)
    branch_ids = [item["id"] for item in items if item["kind"] in ("project", "question")]
    if branch_ids:
        parent_key = case(
            (record.kind == "question", record.payload["project_id"].astext),
            else_=record.payload["context_id"].astext,
        )
        counts = await session.execute(
            select(parent_key, func.count())
            .where(*owned, record.kind.in_(("question", "usage")), parent_key.in_(branch_ids))
            .group_by(parent_key)
        )
        lookup = {key: count for key, count in counts}
        for item in items:
            item["child_count"] = lookup.get(item["id"], 0)
    return {**page(items, total, offset), "independent_total": independent_total}


async def placement_paths(
    session: AsyncSession, principal: Principal, positions: list[KnowledgeRecord]
) -> list[dict[str, Any]]:
    """Resolve only the ancestors of the requested page; never promote missing ancestors."""
    cached = {str(row.id): row for row in positions}
    pending = {row.payload["parent_id"] for row in positions if row.payload["parent_id"]}
    for _ in range(64):
        pending -= cached.keys()
        if not pending:
            break
        parents = list(
            await session.scalars(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.user_id == principal.user_id,
                    KnowledgeRecord.kind == "placement",
                    KnowledgeRecord.status.not_in(INACTIVE),
                    KnowledgeRecord.id.in_(pending),
                )
            )
        )
        cached.update({str(row.id): row for row in parents})
        pending = {row.payload["parent_id"] for row in parents if row.payload["parent_id"]}
    ids = {row.payload["entity_id"] for row in cached.values()}
    entities = (
        {
            str(row.id): row
            for row in await session.scalars(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.user_id == principal.user_id,
                    KnowledgeRecord.kind == "entity",
                    KnowledgeRecord.id.in_(ids),
                )
            )
        }
        if ids
        else {}
    )
    paths = []
    for position in positions:
        nodes = []
        current: str | None = str(position.id)
        seen: set[str] = set()
        while current and current in cached and current not in seen:
            seen.add(current)
            row = cached[current]
            target = entities.get(row.payload["entity_id"])
            if target is None or (current != str(position.id) and target.status in INACTIVE):
                break
            nodes.append(node(target))
            current = row.payload["parent_id"]
        paths.append(
            {
                "placement_id": str(position.id),
                "nodes": list(reversed(nodes)),
                "incomplete": current is not None,
            }
        )
    return paths


async def connections(
    session: AsyncSession,
    principal: Principal,
    record_id: UUID,
    section: Literal["domains", "uses"],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    root = await get_record(session, principal.user_id, record_id)
    if root.kind not in ("entity", "relation"):
        raise HTTPException(422, "Connections are available for knowledge and domains")
    record = KnowledgeRecord
    if section == "domains":
        query = select(record).where(
            record.user_id == principal.user_id,
            record.kind == "placement",
            record.status.not_in(INACTIVE),
            record.payload["entity_id"].astext == str(record_id),
        )
        total = (await session.scalar(select(func.count()).select_from(query.subquery()))) or 0
        positions = list(
            await session.scalars(
                query.order_by(record.created_at, record.id).offset(offset).limit(limit)
            )
        )
        return page(await placement_paths(session, principal, positions), total, offset)
    context = aliased(record)
    usage_query = (
        select(record, context)
        .join(context, record.payload["context_id"].astext == context.id.cast(Text))
        .where(
            record.user_id == principal.user_id,
            record.kind == "usage",
            record.status.not_in(INACTIVE),
            record.payload["knowledge_id"].astext == str(record_id),
            context.user_id == principal.user_id,
            context.kind.in_(("project", "question")),
        )
    )
    total = (await session.scalar(select(func.count()).select_from(usage_query.subquery()))) or 0
    rows = (
        await session.execute(
            usage_query.order_by(record.created_at, record.id).offset(offset).limit(limit)
        )
    ).all()
    project_ids = {ctx.payload["project_id"] for _, ctx in rows if ctx.payload.get("project_id")}
    projects = (
        {
            str(row.id): row
            for row in await session.scalars(
                select(record).where(
                    record.user_id == principal.user_id,
                    record.kind == "project",
                    record.id.in_(project_ids),
                )
            )
        }
        if project_ids
        else {}
    )
    items = []
    for use, ctx in rows:
        project = projects.get(ctx.payload.get("project_id"))
        items.append(
            {
                "usage_id": str(use.id),
                "context": node(ctx),
                "project": node(project) if project else None,
                "role": use.payload["role"],
                "knowledge_revision": use.payload["knowledge_revision"],
                "current_revision": root.revision,
                "current_status": root.status,
                "application_note": use.payload["application_note"],
            }
        )
    return page(items, total, offset)
