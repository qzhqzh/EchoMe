"""Shared hybrid retrieval for personal memories."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import String, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory
from app.services.content_safety import find_sensitive_content
from app.services.embedding import get_embedding
from app.services.memory_scope import exclude_projects

ACTIVE_MEMORY_STATUSES = ("active", "ai_review")
DEFAULT_MIN_SOURCE_SCORE = 0.3
DEFAULT_MIN_VECTOR_ONLY_SCORE = 0.5
# Conversational scaffolding is not evidence that a memory concerns the task.
_GENERIC_QUERY_TOKENS = {
    "我们",
    "我们的",
    "我的",
    "你的",
    "一个",
    "当前",
    "相关",
    "以及",
    "或者",
    "包括",
    "进行",
    "怎么",
    "如何",
    "怎样",
    "什么",
    "哪些",
    "有哪些",
    "有哪",
    "查询",
    "搜索",
    "请问",
    "帮我",
    "一下",
    "是否",
    "可以",
    "需要",
    "the",
    "and",
    "for",
    "this",
    "that",
    "with",
    "from",
    "please",
    "about",
    "what",
    "how",
    "my",
    "our",
    "your",
}
_GENERIC_QUERY_TOKENS |= {
    phrase[start : start + width]
    for phrase in _GENERIC_QUERY_TOKENS
    if not phrase.isascii()
    for width in range(2, len(phrase))
    for start in range(len(phrase) - width + 1)
}
# Keep these when they are the topic, but not as sole support for a specific task.
_BROAD_QUERY_TOKENS = {
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
    "知识",
    "领域",
    "用户",
}
QUERY_ALIASES = {
    "git": ("commit", "pull request", "pr", "workflow"),
    "提交": ("git", "commit", "pull request", "pr", "workflow"),
    "流程": ("workflow", "policy"),
    "规范": ("rule", "policy", "workflow"),
    "家庭网络": ("home", "network", "router", "edgeone", "wireguard", "nginx"),
    "网络架构": ("home", "network", "router", "edgeone", "wireguard", "nginx"),
}


def _term_pattern(token: str) -> str:
    """Literal ASCII terms have the same boundaries in Python and PostgreSQL."""
    escaped = re.escape(token)
    # ASCII boundaries also allow technical terms next to Chinese text and preserve
    # punctuation in C++, C#, host names and identifiers. `ai` must not match `detail`.
    return rf"(^|[^a-z0-9_]){escaped}($|[^a-z0-9_])"


def _term_matches(token: str, text: str) -> bool:
    return bool(re.search(_term_pattern(token), text)) if token.isascii() else token in text


def _relevance_tokens(tokens: set[str]) -> set[str]:
    return {token.lower() for token in tokens} - _GENERIC_QUERY_TOKENS


def _topic_tokens(tokens: set[str]) -> set[str]:
    specific = tokens - _BROAD_QUERY_TOKENS
    return specific if specific else tokens


def _sql_term_match(field: Any, token: str) -> Any:
    if token.isascii():
        return field.op("~")(_term_pattern(token))
    escaped = token.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return field.like(f"%{escaped}%", escape="\\")


@dataclass(frozen=True)
class RankedMemory:
    memory: Memory
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryRetrievalResult:
    items: list[RankedMemory]
    total_candidates: int
    trace: dict[str, Any] = field(default_factory=dict)


def memory_query_tokens(query: str) -> list[str]:
    """Split a query into stable English tokens and overlapping Chinese n-grams."""
    lowered = query.lower()
    if len(lowered) > 2048:
        lowered = f"{lowered[:1024]} {lowered[-1024:]}"
    tokens = {token for token in re.findall(r"[A-Za-z0-9_+#.-]{2,}", lowered) if len(token) <= 64}
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        if len(chunk) <= 32:
            tokens.add(chunk)
        for width in (2, 3, 4):
            tokens.update(chunk[index : index + width] for index in range(len(chunk) - width + 1))
    alias_tokens: set[str] = set()
    for marker, aliases in QUERY_ALIASES.items():
        if _term_matches(marker, lowered):
            alias_tokens.update(aliases)
    tokens.update(alias_tokens)
    stop_tokens = {"我的", "怎样", "怎么", "什么", "如何", "规则", "the", "and", "for"}
    filtered = (token for token in tokens if len(token) >= 2 and token not in stop_tokens)
    return sorted(
        filtered,
        key=lambda token: (token in alias_tokens, len(token), token),
        reverse=True,
    )[:64]


def _independent_matches(tokens: set[str], text: str) -> list[str]:
    """Keep the longest non-overlapping lexical signals to avoid n-gram inflation."""
    matches: list[str] = []
    occupied: list[tuple[int, int]] = []
    for token in sorted(tokens, key=lambda item: (len(item), item), reverse=True):
        if any(token in selected or selected in token for selected in matches):
            continue
        pattern = re.escape(token)
        if token.isascii():
            # Lookarounds keep the returned span on the term itself; neighboring
            # delimiters are not evidence and must not consume another term's span.
            pattern = rf"(?<![a-z0-9_]){pattern}(?![a-z0-9_])"
        spans = [match.span() for match in re.finditer(pattern, text)]
        if not any(
            all(end <= used_start or start >= used_end for used_start, used_end in occupied)
            for start, end in spans
        ):
            continue
        matches.append(token)
        # Reserve every occurrence so repeating one phrase cannot provide a new
        # independent signal through an overlapping fragment such as 与基/基础设施.
        occupied.extend(spans)
    return matches


def lexical_memory_similarity(
    query_tokens: set[str],
    *,
    title: str,
    tags: list[str],
    content: str,
) -> float:
    """Score memory-shaped text using the same lexical signals as live retrieval."""
    query_tokens = _relevance_tokens(query_tokens)
    if not query_tokens:
        return 0.0
    lowered_title = title.lower()
    lowered_tags = " ".join(tags).lower()
    lowered_content = content.lower()
    title_matches = _independent_matches(query_tokens, lowered_title)
    tag_matches = _independent_matches(query_tokens - set(title_matches), lowered_tags)
    content_matches = _independent_matches(
        query_tokens - set(title_matches) - set(tag_matches), lowered_content
    )
    if not _topic_tokens(query_tokens).intersection(title_matches + tag_matches + content_matches):
        return 0.0
    return min(
        1.0,
        0.45 * len(title_matches) + 0.35 * len(tag_matches) + 0.18 * len(content_matches),
    )


async def retrieve_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int,
    min_source_score: float = DEFAULT_MIN_SOURCE_SCORE,
    statuses: tuple[str, ...] = ACTIVE_MEMORY_STATUSES,
    memory_type: str | None = None,
    layer: str | None = None,
    tags: list[str] | None = None,
    global_only: bool = False,
    project_scope_ids: list[str] | None = None,
    embedding_timeout_seconds: float = 3.0,
    discovery: bool = False,
) -> MemoryRetrievalResult:
    """Combine bounded recall with conservative admission of unsupported vector hits.

    Scores below the default source threshold explicitly request broad retrieval;
    otherwise vector-only results need stronger support than the candidate floor.
    The final 70/30 score remains a ranking score, not a calibrated probability.
    """
    filters = [Memory.user_id == user_id, Memory.status.in_(statuses)]
    if memory_type:
        filters.append(Memory.type == memory_type)
    if layer:
        filters.append(Memory.layer == layer)
    for tag in tags or []:
        filters.append(Memory.tags.contains([tag]))
    if global_only:
        filters.append(Memory.scope_global.is_(True))
    elif project_scope_ids:
        filters.append(
            or_(
                Memory.scope_global.is_(True),
                *(Memory.scope_projects.contains([item]) for item in project_scope_ids),
            )
        )

    if project_scope_ids:
        filters.append(exclude_projects(project_scope_ids))

    total_result = await session.execute(select(func.count()).select_from(Memory).where(*filters))
    total_candidates = total_result.scalar_one()
    if discovery:
        from app.services.discovery_query import discovery_query_tokens

        query_token_list = discovery_query_tokens(query)
    else:
        query_token_list = memory_query_tokens(query)
    query_tokens = _relevance_tokens(set(query_token_list))
    query_token_list = [token for token in query_token_list if token in _topic_tokens(query_tokens)]
    min_vector_only_score = (
        max(min_source_score, DEFAULT_MIN_VECTOR_ONLY_SCORE)
        if min_source_score >= DEFAULT_MIN_SOURCE_SCORE
        else min_source_score
    )
    if discovery:
        # Automatic delivery needs stronger semantic evidence than optional
        # broad/manual recall. Keep the semantic channel for paraphrases, and
        # never apply this threshold to explicit search/context requests.
        min_vector_only_score = max(min_vector_only_score, 0.6)

    vector_scores: dict[uuid.UUID, tuple[Memory, float]] = {}
    sensitive_query = bool(find_sensitive_content(query))
    if sensitive_query:
        query_embedding = None
    else:
        try:
            query_embedding = await asyncio.wait_for(
                get_embedding(query[:8000]),
                timeout=embedding_timeout_seconds,
            )
        except TimeoutError:
            query_embedding = None
    if query_embedding is not None:
        vector_query = (
            select(
                Memory,
                Memory.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(*filters, Memory.embedding.isnot(None))
            .order_by("distance")
            .limit(max(limit * 3, 10))
        )
        vector_result = await session.execute(vector_query)
        for row in vector_result:
            similarity = 1.0 - float(row[1])
            if similarity >= min_source_score:
                vector_scores[row[0].id] = (row[0], similarity)

    candidates: list[Memory] = []
    if query_tokens:
        title_field = func.lower(Memory.title)
        content_field = func.lower(Memory.content)
        tags_field = func.lower(Memory.tags.cast(String))
        terms = query_token_list[:24]
        relevance: Any = sum(
            case((_sql_term_match(title_field, token), 5), else_=0)
            + case((_sql_term_match(tags_field, token), 4), else_=0)
            + case((_sql_term_match(content_field, token), 1), else_=0)
            for token in terms
        )
        lexical_query = (
            select(Memory)
            .where(
                *filters,
                or_(
                    *[
                        _sql_term_match(field, token)
                        for token in terms
                        for field in (title_field, content_field, tags_field)
                    ]
                ),
            )
            .order_by(relevance.desc(), Memory.priority.desc(), Memory.updated_at.desc())
            .limit(min(max(limit * 20, 200), 2000))
        )
        candidate_result = await session.execute(lexical_query)
        candidates = list(candidate_result.scalars().all())
    # A vector hit can have genuine lexical evidence outside the bounded SQL
    # shortlist. Score the union so those memories are not misclassified as vector-only.
    candidates_by_id = {memory.id: memory for memory, _ in vector_scores.values()}
    candidates_by_id.update((memory.id, memory) for memory in candidates)
    lexical_scores = {
        memory.id: score
        for memory in candidates_by_id.values()
        if (
            score := lexical_memory_similarity(
                query_tokens,
                title=memory.title,
                tags=memory.tags or [],
                content=memory.content,
            )
        )
        >= min_source_score
        and score > 0.0
    }

    ranked: list[RankedMemory] = []
    weak_vector_only_count = 0
    for memory_id in set(vector_scores) | set(lexical_scores):
        vector_score = vector_scores.get(memory_id, (None, 0.0))[1]
        lexical_score = lexical_scores.get(memory_id, 0.0)
        lexical_supported = bool(lexical_score)
        if discovery:
            # Two incidental body words are weak support. A title/tag match,
            # multiple independent facts or corroborating semantics are enough.
            lexical_supported = lexical_score >= 0.45 or (
                lexical_score >= min_source_score and vector_score >= 0.55
            )
        if not lexical_supported and vector_score < min_vector_only_score:
            weak_vector_only_count += 1
            continue
        memory = candidates_by_id[memory_id]
        reasons = []
        if vector_score:
            reasons.append("vector")
        if lexical_score:
            reasons.append("lexical")
        ranked.append(
            RankedMemory(
                memory=memory,
                score=round(vector_score * 0.7 + lexical_score * 0.3, 4),
                reasons=tuple(reasons),
            )
        )
    ranked.sort(
        key=lambda item: (item.score, item.memory.priority, item.memory.updated_at),
        reverse=True,
    )
    selected = ranked[:limit]
    return MemoryRetrievalResult(
        items=selected,
        total_candidates=total_candidates,
        trace={
            "strategy": "hybrid_memory",
            "vector_available": query_embedding is not None,
            "sensitive_query_embedding_skipped": sensitive_query,
            "vector_count": len(vector_scores),
            "lexical_candidate_count": len(candidates),
            "lexical_count": len(lexical_scores),
            "min_source_score": min_source_score,
            "min_vector_only_score": min_vector_only_score,
            "weak_vector_only_filtered": weak_vector_only_count,
            "query_token_count": len(query_token_list),
            "selected_count": len(selected),
        },
    )
