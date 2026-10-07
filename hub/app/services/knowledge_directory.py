"""Read-only, paged directory branches and search paths for the knowledge UI."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Integer, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.knowledge import KnowledgeRecord
from app.schemas.knowledge import KnowledgeQuery
from app.services.knowledge import INACTIVE, Principal, get_record, query_records


def entry(entity: KnowledgeRecord, placement: KnowledgeRecord | None) -> dict[str, Any]:
    return {
        "entity_id": str(entity.id),
        "placement_id": str(placement.id) if placement else None,
        "name": entity.payload["name"],
        "entity_kind": entity.payload["entity_kind"],
        "summary": entity.payload.get("summary", ""),
        "child_count": 0,
    }


async def directory_search(
    session: AsyncSession, principal: Principal, search: str, offset: int, limit: int
) -> dict[str, Any]:
    matches = await query_records(
        session,
        principal,
        KnowledgeQuery(kind="entity", filters={"entity_kind": "topic"}, offset=offset, limit=limit),
        search=search,
    )
    ids = [item["id"] for item in matches["items"]]
    position = aliased(KnowledgeRecord)
    entity = aliased(KnowledgeRecord)
    positions = (
        select(position, entity)
        .join(entity, position.payload["entity_id"].astext == entity.id.cast(Text))
        .where(
            position.user_id == principal.user_id,
            position.kind == "placement",
            position.status.not_in(INACTIVE),
            entity.user_id == principal.user_id,
            entity.kind == "entity",
            entity.status.not_in(INACTIVE),
        )
    )
    initial = (await session.execute(positions.where(entity.id.in_(ids)))).all() if ids else []
    cached = {str(p.id): (p, e) for p, e in initial}
    pending = {p.payload["parent_id"] for p, _ in initial if p.payload["parent_id"]}
    # The write model rejects cycles. Bound unusual imported depth as an extra read safeguard.
    for _ in range(64):
        pending -= cached.keys()
        if not pending:
            break
        parents = (await session.execute(positions.where(position.id.in_(pending)))).all()
        cached.update({str(p.id): (p, e) for p, e in parents})
        pending = {p.payload["parent_id"] for p, _ in parents if p.payload["parent_id"]}
    items = []
    for match in matches["items"]:
        paths = []
        for position_row, _ in initial:
            if position_row.payload["entity_id"] != match["id"]:
                continue
            names: list[str] = []
            current: str | None = str(position_row.id)
            seen: set[str] = set()
            while current and current in cached and current not in seen:
                seen.add(current)
                row, target = cached[current]
                names.append(target.payload["name"])
                current = row.payload["parent_id"]
            paths.append({"names": list(reversed(names)), "incomplete": current is not None})
        items.append(
            {
                "entity_id": match["id"],
                "placement_id": None,
                "name": match["data"]["name"],
                "entity_kind": "topic",
                "summary": match["data"].get("summary", ""),
                "child_count": 0,
                "paths": paths,
            }
        )
    return {
        "items": items,
        "total": matches["total"],
        "next_offset": matches["next_offset"],
        "unplaced_total": 0,
    }


async def directory_branch(
    session: AsyncSession,
    principal: Principal,
    *,
    parent_id: UUID | None = None,
    unplaced: bool = False,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    if (parent_id and (unplaced or search)) or (unplaced and search):
        raise HTTPException(422, "Choose a directory branch, unplaced domains or search")
    if search:
        return await directory_search(session, principal, search, offset, limit)
    if parent_id:
        parent = await get_record(session, principal.user_id, parent_id)
        if parent.kind != "placement" or parent.status in INACTIVE:
            raise HTTPException(404, "Directory position not found")
        parent_entity = await get_record(session, principal.user_id, parent.payload["entity_id"])
        if parent_entity.status in INACTIVE:
            raise HTTPException(404, "Directory entity is inactive")

    position = aliased(KnowledgeRecord)
    entity = aliased(KnowledgeRecord)
    unplaced_query = select(entity).where(
        entity.user_id == principal.user_id,
        entity.kind == "entity",
        entity.status.not_in(INACTIVE),
        entity.payload["entity_kind"].astext == "topic",
        ~select(position.id)
        .where(
            position.user_id == principal.user_id,
            position.kind == "placement",
            position.status.not_in(INACTIVE),
            position.payload["entity_id"].astext == entity.id.cast(Text),
        )
        .exists(),
    )
    unplaced_total = 0
    if parent_id is None:
        unplaced_total = (
            await session.scalar(select(func.count()).select_from(unplaced_query.subquery()))
        ) or 0
    if unplaced:
        entities = await session.scalars(
            unplaced_query.order_by(entity.created_at, entity.id).offset(offset).limit(limit)
        )
        items = [entry(row, None) for row in entities]
        total = unplaced_total
    else:
        branch = (
            select(position, entity)
            .join(entity, position.payload["entity_id"].astext == entity.id.cast(Text))
            .where(
                position.user_id == principal.user_id,
                position.kind == "placement",
                position.status.not_in(INACTIVE),
                entity.user_id == principal.user_id,
                entity.kind == "entity",
                entity.status.not_in(INACTIVE),
                position.payload["parent_id"].astext == str(parent_id)
                if parent_id
                else position.payload["parent_id"].astext.is_(None),
            )
        )
        total = (await session.scalar(select(func.count()).select_from(branch.subquery()))) or 0
        rows = (
            await session.execute(
                branch.order_by(
                    position.payload["sort_order"].astext.cast(Integer),
                    entity.payload["name"].astext,
                    position.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        items = [entry(e, p) for p, e in rows]
        position_ids = [str(p.id) for p, _ in rows]
        if position_ids:
            parent_key = position.payload["parent_id"].astext
            child_counts = (
                await session.execute(
                    select(parent_key, func.count())
                    .join(entity, position.payload["entity_id"].astext == entity.id.cast(Text))
                    .where(
                        position.user_id == principal.user_id,
                        position.kind == "placement",
                        position.status.not_in(INACTIVE),
                        parent_key.in_(position_ids),
                        entity.user_id == principal.user_id,
                        entity.kind == "entity",
                        entity.status.not_in(INACTIVE),
                    )
                    .group_by(parent_key)
                )
            ).all()
            counts: dict[str, int] = {parent: count for parent, count in child_counts}
            for item in items:
                item["child_count"] = counts.get(item["placement_id"], 0)
    next_offset = offset + len(items)
    return {
        "items": items,
        "total": total,
        "next_offset": next_offset if next_offset < total else None,
        "unplaced_total": unplaced_total,
    }
