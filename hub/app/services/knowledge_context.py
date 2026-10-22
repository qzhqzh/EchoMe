"""Small discovery references; snippets never become verified facts or constraints."""

import re
from itertools import combinations
from typing import Any

from sqlalchemy import Text, and_, case, false, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.knowledge import KnowledgeRecord, KnowledgeReference
from app.models.scene_knowledge import SceneKnowledge, SceneKnowledgeEntry
from app.services.memory_retrieval import memory_query_tokens

MAX_REFS = 4
MAX_TOKENS = 24
TITLE_CHARS = 160
SNIPPET_CHARS = 240
SOURCE_CHARS = 320
_GENERIC = {
    "请问",
    "帮我",
    "看看",
    "一下",
    "查询",
    "搜索",
    "关于",
    "这个",
    "那个",
    "一些",
    "是否",
    "知识",
    "记忆",
    "内容",
    "问题",
    "当前",
    "please",
    "search",
    "find",
    "memory",
    "knowledge",
}
_BROAD = {
    "ai",
    "llm",
    "model",
    "models",
    "system",
    "project",
    "data",
    "feature",
    "workflow",
    "模型",
    "系统",
    "项目",
    "数据",
    "功能",
    "工作",
    "流程",
}
BODY_PROXIMITY_CHARS = 80
MAX_SHORT_BODY_TERMS = 8


def _tokens(query: str) -> list[str]:
    tokens = [
        token
        for token in memory_query_tokens(query)
        if token not in _GENERIC and re.search(r"[a-z\u4e00-\u9fff]", token)
    ]
    # Broad terms can describe a title when asked alone, but must not drown out
    # the more specific subject of a multi-term task.
    if len(tokens) > 1:
        tokens = [token for token in tokens if token not in _BROAD]
    return tokens[:MAX_TOKENS]


def _term_pattern(token: str) -> str:
    pattern = re.escape(token)
    if token.isascii():
        # PostgreSQL word boundaries avoid e.g. "train" matching "constraint".
        return r"\m" + pattern + r"\M"
    return pattern


def _term_match(field: Any, token: str) -> Any:
    if token.isascii():
        return field.op("~*")(_term_pattern(token))
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.lower(field).like("%" + escaped + "%", escape="\\")


def _match(title: Any, aliases: Any, body: Any, tokens: list[str]) -> tuple[Any, Any]:
    """Require a useful index match or concentrated body evidence, never word count.

    One four-character Chinese phrase or non-broad Latin term can match the body.
    Short terms need two independent matches no more than 80 characters apart.
    A field contributes one score tier: overlapping n-grams never add votes.
    """
    title_match = or_(*(_term_match(title, token) for token in tokens))
    alias_match = or_(*(_term_match(aliases, token) for token in tokens))
    strong = [token for token in tokens if len(token) >= 4 and token not in _BROAD]
    body_strong = or_(False, *(_term_match(body, token) for token in strong))
    short: list[str] = []
    for token in sorted(tokens, key=lambda value: (-len(value), value)):
        if len(token) >= 4 or token in _BROAD:
            continue
        if any(token in chosen or chosen in token for chosen in short):
            continue
        short.append(token)
        if len(short) >= MAX_SHORT_BODY_TERMS:
            break
    adjacent = []
    for first, second in combinations(short, 2):
        if first in second or second in first:
            continue
        for left, right in ((first, second), (second, first)):
            adjacent.append(
                _term_pattern(left)
                + ".{0,"
                + str(BODY_PROXIMITY_CHARS)
                + "}"
                + _term_pattern(right)
            )
    body_near = body.op("~*")("(?s)(?:" + "|".join(adjacent) + ")") if adjacent else false()
    return (
        or_(title_match, alias_match, body_strong, body_near),
        case((title_match, 5), (alias_match, 4), (body_strong, 2), (body_near, 1), else_=0),
    )


def _reference(row: RowMapping, source: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": str(row["id"]),
        "kind": row["kind"] if source == "knowledge" else "scene_entry",
        "revision": row["revision"],
        "source": source,
        "title": row["title"],
        "snippet": row["snippet"],
        "status": row["status"],
        "needs_expansion": True,
        "review_state": "disputed" if source == "knowledge" and row["disputed"] else "unchecked",
    }
    if source == "knowledge":
        item["read"] = {
            "tool": "echome_knowledge_read",
            "arguments": {
                "action": "get",
                "record_id": item["id"],
                "data": {"revision": row["revision"]},
            },
        }
    else:
        item.update(
            scene_id=str(row["scene_id"]),
            category=row["category"],
            source_ref=row["source_ref"],
            evidence_at=row["evidence_at"].isoformat() if row["evidence_at"] else None,
            read={
                "tool": "echome_scene_read",
                "arguments": {"action": "get", "selector": row["slug"]},
            },
        )
    return item


async def discover_knowledge_refs(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    project_id: str | None = None,
    limit: int = MAX_REFS,
) -> list[dict[str, Any]]:
    """Run two bounded reads, with full validation deferred to explicit expansion.

    Knowledge is shared across this owner's projects. Scene facts are only global
    or scoped to the already resolved project; no project is inferred here.
    The caller owns transaction/savepoint handling for an optional lookup failure.
    """
    limit = min(max(limit, 0), MAX_REFS)
    tokens = _tokens(query)
    if not tokens or not limit:
        return []

    record = KnowledgeRecord
    title = func.coalesce(
        record.payload["name"].astext,
        record.payload["title"].astext,
        record.payload["statement_md"].astext,
        "",
    )
    body = func.concat_ws(
        " ",
        record.payload["summary"].astext,
        record.payload["body_md"].astext,
        record.payload["statement_md"].astext,
        record.payload["personal_note"].astext,
    )
    matched, rank = _match(title, record.payload["aliases"].astext, body, tokens)
    review = aliased(record)
    disputed = (
        select(review.id)
        .join(
            KnowledgeReference,
            and_(
                KnowledgeReference.owner_id == review.id,
                KnowledgeReference.owner_revision == review.revision,
                KnowledgeReference.user_id == review.user_id,
            ),
        )
        .where(
            review.user_id == user_id,
            review.kind == "review",
            review.status.in_(("open", "disputed", "snoozed")),
            review.payload["issue_kind"].astext.in_(
                ("conflict", "overgeneralization", "page_mismatch")
            ),
            KnowledgeReference.target_id == record.id,
            KnowledgeReference.user_id == user_id,
        )
        .correlate(record)
        .exists()
    )
    knowledge = (
        (
            await session.execute(
                select(
                    record.id,
                    record.kind,
                    record.revision,
                    record.status,
                    record.updated_at,
                    func.left(title, TITLE_CHARS).label("title"),
                    func.left(body, SNIPPET_CHARS).label("snippet"),
                    disputed.label("disputed"),
                    rank.label("rank"),
                )
                .where(
                    record.user_id == user_id,
                    record.kind.in_(("entity", "relation", "page")),
                    record.status == "active",
                    matched,
                )
                .order_by(rank.desc(), record.updated_at.desc(), record.id)
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )

    scene, entry = SceneKnowledge, SceneKnowledgeEntry
    scene_title = func.coalesce(scene.title, "")
    scene_body = func.concat_ws(" ", scene.summary, entry.content)
    scene_match, scene_rank = _match(scene_title, scene.aliases.cast(Text), scene_body, tokens)
    scene_scope: ColumnElement[bool] = scene.project_id.is_(None)
    if project_id:
        scene_scope = or_(scene_scope, scene.project_id == project_id)
    scenes = (
        (
            await session.execute(
                select(
                    entry.id,
                    entry.revision,
                    entry.status,
                    entry.updated_at,
                    entry.category,
                    entry.evidence_at,
                    scene.id.label("scene_id"),
                    scene.slug,
                    func.left(scene_title, TITLE_CHARS).label("title"),
                    func.left(entry.content, SNIPPET_CHARS).label("snippet"),
                    func.left(entry.source_ref, SOURCE_CHARS).label("source_ref"),
                    scene_rank.label("rank"),
                )
                .join(scene, and_(scene.id == entry.scene_id, scene.user_id == entry.user_id))
                .where(
                    scene.user_id == user_id,
                    entry.user_id == user_id,
                    scene.status == "active",
                    entry.status == "active",
                    scene_scope,
                    scene_match,
                )
                .order_by(scene_rank.desc(), entry.updated_at.desc(), entry.id)
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )
    candidates = [(row, "knowledge") for row in knowledge] + [(row, "scene") for row in scenes]
    candidates.sort(
        key=lambda item: (-item[0]["rank"], -item[0]["updated_at"].timestamp(), str(item[0]["id"]))
    )
    return [_reference(row, source) for row, source in candidates[:limit]]
