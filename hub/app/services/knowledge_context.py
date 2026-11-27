"""Small discovery references; snippets never become verified facts or constraints."""

import re
from itertools import combinations
from typing import Any

from sqlalchemy import Text, and_, case, false, func, literal, not_, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.knowledge import KnowledgeRecord, KnowledgeReference
from app.models.scene_knowledge import SceneKnowledge, SceneKnowledgeEntry
from app.services.memory_retrieval import memory_query_tokens

MAX_REFS = 4
MAX_DISCOVERY_CANDIDATES = 12
MAX_DISCOVERY_SCENE_REFS = 2
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
_INDEX_OPERATIONS = {
    "安装", "部署", "更新", "发布", "测试", "配置", "路径", "文档", "说明", "使用",
    "默认", "支持", "直接", "相关", "最新", "操作", "目录", "文件", "版本", "下载",
}


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


def _direct_tokens(query: str, tokens: list[str]) -> list[str]:
    """Rank entry-specific evidence using the task itself, not expanded aliases."""
    lowered = query.lower()
    return [
        token
        for token in tokens
        if (
            re.search(r"(?<![a-z0-9_])" + re.escape(token) + r"(?![a-z0-9_])", lowered)
            if token.isascii()
            else token in lowered
        )
    ]


def _entry_rank(content: Any, tokens: list[str], *, weight_identifiers: bool = True) -> Any:
    """Count independent content matches, preferring explicitly named identifiers."""
    terms = list(dict.fromkeys(tokens))
    signals = []
    for token in terms:
        # Suppress overlapping n-grams only if their containing term also
        # matches this entry. A longer query phrase need not occur verbatim.
        containing = [other for other in terms if token != other and token in other]
        match = _term_match(content, token)
        if containing:
            match = and_(match, not_(or_(*(_term_match(content, other) for other in containing))))
        weight = 3 if weight_identifiers and any(character.isdigit() for character in token) else 1
        signals.append(case((match, weight), else_=0))
    return sum(signals) if signals else literal(0)


def _discovery_match(
    title: Any, aliases: Any, body: Any, query: str, tokens: list[str],
) -> tuple[Any, Any, Any, Any]:
    """Unsolicited indexes need a topic, not one incidental operational phrase."""
    from app.services.discovery_query import discovery_named_terms

    named = discovery_named_terms(query)
    direct = [token for token in _direct_tokens(query, tokens) if token not in _INDEX_OPERATIONS]
    if named:
        direct = [token for token in direct if not token.isascii() or token in named or token.isdigit()]
    title_match = or_(False, *(_term_match(title, token) for token in direct))
    alias_match = or_(False, *(_term_match(aliases, token) for token in direct))
    body_count = _entry_rank(body, direct, weight_identifiers=False)
    body_rank = _entry_rank(body, direct)
    body_match = body_count >= 2
    if named:
        named_match = or_(*(_term_match(body, token) for token in named))
        body_match = and_(body_match, named_match)
        # A short request naming one concrete tool/domain is already specific;
        # requiring a second topic would lose e.g. "new FlClash configuration".
        if len(named) == 1:
            body_match = or_(body_match, named_match)
        # A short generic label such as "域名" cannot identify a named product.
        # A concrete Chinese topic (e.g. 家庭网络) remains useful background even
        # when its overview does not repeat every newly mentioned tool name.
        chinese_topics = [token for token in direct if not token.isascii() and len(token) >= 4]
        title_topic = or_(False, *(_term_match(title, token) for token in [*named, *chinese_topics]))
        alias_topic = or_(False, *(_term_match(aliases, token) for token in [*named, *chinese_topics]))
        title_match = and_(title_match, or_(title_topic, named_match))
        alias_match = and_(alias_match, or_(alias_topic, named_match))
    identifiers = [token for token in direct if token.isdigit() and len(token) >= 3]
    identifier_match = or_(False, *(_term_match(body, token) for token in identifiers))
    body_match = or_(body_match, identifier_match)
    rank = case((title_match, 5), (alias_match, 4), (body_match, 2), else_=0)
    return (
        or_(title_match, alias_match, body_match),
        rank + case((identifier_match, 3), else_=0),
        body_rank,
        title_match,
    )


def _overview_requested(query: str) -> bool:
    return bool(re.search(r"了解|概览|总览|介绍|\b(?:overview|background|understand)\b", query, re.I))


def _diverse_candidates(
    candidates: list[tuple[RowMapping, str]], limit: int,
) -> list[tuple[RowMapping, str]]:
    """Prevent one scene from monopolizing a small index without filling weak sources."""
    selected: list[tuple[RowMapping, str]] = []
    selected_ids: set[tuple[str, str]] = set()
    scene_counts: dict[str, int] = {}

    def add(candidate: tuple[RowMapping, str]) -> None:
        row, source = candidate
        identity = (source, str(row["id"]))
        scene_id = str(row["scene_id"]) if source == "scene" else None
        if len(selected) >= limit or identity in selected_ids:
            return
        if scene_id is not None and scene_counts.get(scene_id, 0) >= MAX_DISCOVERY_SCENE_REFS:
            return
        selected.append(candidate)
        selected_ids.add(identity)
        if scene_id is not None:
            scene_counts[scene_id] = scene_counts.get(scene_id, 0) + 1

    if limit >= 2:
        # Rank 2 requires direct topic support; rank 1 is only weak evidence.
        # Reserve both sources only when both contain independently useful hits.
        best = {
            source: next((item for item in candidates if item[1] == source and item[0]["rank"] >= 2), None)
            for source in ("knowledge", "scene")
        }
        if all(best.values()):
            for item in candidates:
                if any(item is candidate for candidate in best.values()):
                    add(item)
    for candidate in candidates:
        add(candidate)
    selected_ids = {(source, str(row["id"])) for row, source in selected}
    return [item for item in candidates if (item[1], str(item[0]["id"])) in selected_ids]


def _reference(row: RowMapping, source: str, *, discovery: bool = False) -> dict[str, Any]:
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
    if discovery:
        arguments = item["read"]["arguments"]
        if source == "knowledge":
            arguments["view"] = "full"
        else:
            arguments["entry_id"] = item["id"]
            arguments["view"] = "compact"
    return item


async def discover_knowledge_refs(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    project_id: str | None = None,
    limit: int = MAX_REFS,
    discovery: bool = False,
) -> list[dict[str, Any]]:
    """Run two bounded reads, with full validation deferred to explicit expansion.

    Knowledge is shared across this owner's projects. Scene facts are only global
    or scoped to the already resolved project; no project is inferred here.
    The caller owns transaction/savepoint handling for an optional lookup failure.
    """
    limit = min(max(limit, 0), MAX_REFS)
    if discovery:
        from app.services.discovery_query import discovery_query_tokens

        tokens = [token for token in discovery_query_tokens(query) if token not in _GENERIC][
            :MAX_TOKENS
        ]
    else:
        tokens = _tokens(query)
    if not tokens or not limit:
        return []
    candidate_limit = min(limit * 3, MAX_DISCOVERY_CANDIDATES) if discovery else limit

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
    content_rank, overview_rank = None, None
    if discovery:
        matched, rank, content_rank, title_match = _discovery_match(
            title, record.payload["aliases"].astext, body, query, tokens,
        )
        overview_rank = case((
            and_(
                title_match,
                record.kind == "page",
                record.payload["bindings"].contains([{"role": "overview"}]),
                _overview_requested(query),
            ), 1,
        ), else_=0)
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
                    *([content_rank.label("content_rank")] if content_rank is not None else []),
                    *([overview_rank.label("overview_rank")] if overview_rank is not None else []),
                )
                .where(
                    record.user_id == user_id,
                    record.kind.in_(("entity", "relation", "page")),
                    record.status == "active",
                    matched,
                )
                .order_by(
                    *([overview_rank.desc()] if overview_rank is not None else []),
                    rank.desc(),
                    *([content_rank.desc()] if content_rank is not None else []),
                    record.updated_at.desc(), record.id,
                )
                .limit(candidate_limit)
            )
        )
        .mappings()
        .all()
    )

    scene, entry = SceneKnowledge, SceneKnowledgeEntry
    scene_title = func.coalesce(scene.title, "")
    scene_body = func.concat_ws(" ", scene.summary, entry.content)
    scene_match, scene_rank = _match(scene_title, scene.aliases.cast(Text), scene_body, tokens)
    entry_rank = None
    if discovery:
        scene_match, scene_rank, entry_rank, _ = _discovery_match(
            scene_title, scene.aliases.cast(Text), entry.content, query, tokens,
        )
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
                    *([entry_rank.label("entry_rank")] if entry_rank is not None else []),
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
                .order_by(
                    *([entry_rank.desc()] if entry_rank is not None else []),
                    scene_rank.desc(), entry.updated_at.desc(), entry.id,
                )
                .limit(candidate_limit)
            )
        )
        .mappings()
        .all()
    )
    candidates = [(row, "knowledge") for row in knowledge] + [(row, "scene") for row in scenes]
    candidates.sort(
        key=lambda item: (
            -item[0].get("overview_rank", 0) if discovery else 0,
            -item[0]["rank"],
            -item[0].get("content_rank", item[0].get("entry_rank", 0)) if discovery else 0,
            -item[0]["updated_at"].timestamp(), str(item[0]["id"]),
        )
    )
    selected = _diverse_candidates(candidates, limit) if discovery else candidates[:limit]
    return [_reference(row, source, discovery=discovery) for row, source in selected]
