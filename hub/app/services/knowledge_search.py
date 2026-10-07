"""Owner-scoped discovery across user-facing knowledge objects, with exact page counts."""

import re
from typing import Any, Literal

from sqlalchemy import Text, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.knowledge import KnowledgeOverview, KnowledgeRecord, KnowledgeReference
from app.services.knowledge import INACTIVE, Principal
from app.services.knowledge_navigation import node, page, placement_paths

SearchCategory = Literal[
    "all", "projects", "questions", "domains", "knowledge", "pages", "sources", "deliverables"
]


def excerpt(text: str, query: str) -> str:
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"!?\[([^\]]+)\]\([^\n)]*\)", r"\1", text)
    plain = re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()
    index = plain.casefold().find(query.casefold())
    start = max(0, index - 45)
    return (
        ("…" if start else "")
        + plain[start : start + 180]
        + ("…" if len(plain) > start + 180 else "")
    )


async def search_knowledge(
    session: AsyncSession,
    principal: Principal,
    text: str,
    category: SearchCategory,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {**page([], 0, 0), "counts": {}, "query": text}
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = "%" + escaped + "%"
    record = KnowledgeRecord
    document = aliased(record)
    owner = aliased(record)
    title = func.coalesce(
        record.payload["name"].astext,
        record.payload["title"].astext,
        record.payload["statement_md"].astext,
        "",
    )
    category_key = case(
        (record.kind == "project", "projects"),
        (record.kind == "question", "questions"),
        (and_(record.kind == "entity", record.payload["entity_kind"].astext == "topic"), "domains"),
        (record.kind.in_(("entity", "relation")), "knowledge"),
        (record.kind == "page", "pages"),
        (record.kind == "source", "sources"),
        else_="deliverables",
    )
    bound_body = (
        select(document.payload["body_md"].astext)
        .join(
            KnowledgeReference,
            and_(
                KnowledgeReference.owner_id == document.id,
                KnowledgeReference.owner_revision == document.revision,
                KnowledgeReference.user_id == document.user_id,
            ),
        )
        .where(
            KnowledgeReference.target_id == record.id,
            KnowledgeReference.user_id == principal.user_id,
            document.user_id == principal.user_id,
            document.kind == "page",
            document.status.not_in(INACTIVE),
            KnowledgeReference.slot.like("bindings.%"),
            or_(
                document.payload["body_md"].astext.ilike(pattern, escape="\\"),
                document.payload["title"].astext.ilike(pattern, escape="\\"),
            ),
        )
        .correlate(record)
        .order_by(document.updated_at.desc(), document.id)
        .limit(1)
        .scalar_subquery()
    )
    overview = (
        select(KnowledgeOverview.page_id)
        .join(owner, owner.id == KnowledgeOverview.target_id)
        .where(
            KnowledgeOverview.page_id == record.id,
            KnowledgeOverview.user_id == principal.user_id,
            owner.user_id == principal.user_id,
            owner.status.not_in(INACTIVE),
            owner.kind.in_(("project", "question", "entity")),
        )
        .correlate(record)
    )
    fields = (
        "summary",
        "body_md",
        "content_text",
        "resolution_note",
        "description",
        "personal_note",
        "aliases",
        "origin_ref",
    )
    where = [
        record.user_id == principal.user_id,
        record.status.not_in(INACTIVE),
        record.kind.in_(
            ("project", "question", "entity", "relation", "page", "source", "deliverable")
        ),
        ~and_(record.kind == "page", overview.exists()),
        or_(
            title.ilike(pattern, escape="\\"),
            *(record.payload[field].astext.ilike(pattern, escape="\\") for field in fields),
            bound_body.is_not(None),
        ),
    ]
    grouped = await session.execute(
        select(category_key, func.count()).where(*where).group_by(category_key)
    )
    counts = {key: count for key, count in grouped}
    total = sum(counts.values()) if category == "all" else counts.get(category, 0)
    if category != "all":
        where.append(category_key == category)
    rank = case(
        (func.lower(title) == text.lower(), 0),
        (title.ilike(escaped + "%", escape="\\"), 1),
        (title.ilike(pattern, escape="\\"), 2),
        else_=3,
    )
    rows = (
        await session.execute(
            select(record, category_key, bound_body)
            .where(*where)
            .order_by(rank, record.updated_at.desc(), record.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = []
    for row, group, body in rows:
        item = node(row)
        strings = [row.payload.get(field, "") for field in fields if field != "aliases"]
        candidates = [
            value
            for value in strings
            if isinstance(value, str) and text.casefold() in value.casefold()
        ]
        item.update(
            {
                "category": group,
                "snippet": excerpt(
                    candidates[0] if candidates else body or row.payload.get("summary", ""), text
                ),
                "locations": [],
                "location_count": 0,
            }
        )
        items.append(item)

    # Resolve one representative directory path per result in a batch. Multiple locations stay explicit.
    entity_ids = [item["id"] for item in items if item["kind"] == "entity"]
    if entity_ids:
        entity_key = record.payload["entity_id"].astext
        ranked = (
            select(
                record.id.label("id"),
                func.row_number()
                .over(partition_by=entity_key, order_by=(record.created_at, record.id))
                .label("position"),
                func.count().over(partition_by=entity_key).label("total"),
            )
            .where(
                record.user_id == principal.user_id,
                record.kind == "placement",
                record.status.not_in(INACTIVE),
                entity_key.in_(entity_ids),
            )
            .subquery()
        )
        positions = (
            await session.execute(
                select(record, ranked.c.total)
                .join(ranked, ranked.c.id == record.id)
                .where(ranked.c.position == 1)
            )
        ).all()
        paths = await placement_paths(session, principal, [row for row, _ in positions])
        by_entity = {
            row.payload["entity_id"]: (path, count)
            for (row, count), path in zip(positions, paths, strict=True)
        }
        for item in items:
            if item["id"] in by_entity:
                path, count = by_entity[item["id"]]
                item["locations"] = [
                    {"nodes": path["nodes"][:-1], "incomplete": path["incomplete"]}
                ]
                item["location_count"] = count
    project_ids = {row.payload["project_id"] for row, _, _ in rows if row.payload.get("project_id")}
    projects = (
        {
            str(row.id): node(row)
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
    for item, (row, _, _) in zip(items, rows, strict=True):
        if row.payload.get("project_id") in projects:
            item["locations"] = [
                {"nodes": [projects[row.payload["project_id"]]], "incomplete": False}
            ]
    return {**page(items, total, offset), "counts": counts, "query": text}
