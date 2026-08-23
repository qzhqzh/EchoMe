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
from app.services.embedding import get_embedding

ACTIVE_MEMORY_STATUSES = ("active", "ai_review")
QUERY_ALIASES = {
    "git": ("commit", "pull request", "pr", "workflow"),
    "提交": ("git", "commit", "pull request", "pr", "workflow"),
    "流程": ("workflow", "policy"),
    "规范": ("rule", "policy", "workflow"),
    "家庭网络": ("home", "network", "router", "edgeone", "wireguard", "nginx"),
    "网络架构": ("home", "network", "router", "edgeone", "wireguard", "nginx"),
}


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
    tokens = {
        token
        for token in re.findall(r"[A-Za-z0-9_+#.-]{2,}", lowered)
        if len(token) <= 64
    }
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        if len(chunk) <= 32:
            tokens.add(chunk)
        for width in (2, 3, 4):
            tokens.update(chunk[index : index + width] for index in range(len(chunk) - width + 1))
    alias_tokens: set[str] = set()
    for marker, aliases in QUERY_ALIASES.items():
        if marker in lowered:
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
    for token in sorted(tokens, key=lambda item: (len(item), item), reverse=True):
        if token not in text:
            continue
        if any(token in selected or selected in token for selected in matches):
            continue
        matches.append(token)
    return matches


def _lexical_similarity(query_tokens: set[str], memory: Memory) -> float:
    if not query_tokens:
        return 0.0
    title = memory.title.lower()
    tags = " ".join(memory.tags or []).lower()
    content = memory.content.lower()
    title_matches = _independent_matches(query_tokens, title)
    tag_matches = _independent_matches(query_tokens - set(title_matches), tags)
    content_matches = _independent_matches(
        query_tokens - set(title_matches) - set(tag_matches), content
    )
    return min(
        1.0,
        0.45 * len(title_matches)
        + 0.35 * len(tag_matches)
        + 0.18 * len(content_matches),
    )


async def retrieve_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int,
    min_source_score: float = 0.3,
    statuses: tuple[str, ...] = ACTIVE_MEMORY_STATUSES,
    memory_type: str | None = None,
    layer: str | None = None,
    tags: list[str] | None = None,
    global_only: bool = False,
    project_scope_ids: list[str] | None = None,
    embedding_timeout_seconds: float = 3.0,
) -> MemoryRetrievalResult:
    """Combine vector and lexical evidence while preserving graceful degradation."""
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

    total_result = await session.execute(
        select(func.count()).select_from(Memory).where(*filters)
    )
    total_candidates = total_result.scalar_one()
    query_token_list = memory_query_tokens(query)
    query_tokens = set(query_token_list)

    vector_scores: dict[uuid.UUID, tuple[Memory, float]] = {}
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
        patterns = [f"%{token}%" for token in query_token_list[:24]]
        relevance: Any = sum(
            case((title_field.like(pattern), 5), else_=0)
            + case((tags_field.like(pattern), 4), else_=0)
            + case((content_field.like(pattern), 1), else_=0)
            for pattern in patterns
        )
        lexical_query = (
            select(Memory)
            .where(
                *filters,
                or_(
                    *[
                        field.like(pattern)
                        for pattern in patterns
                        for field in (title_field, content_field, tags_field)
                    ]
                ),
            )
            .order_by(relevance.desc(), Memory.priority.desc(), Memory.updated_at.desc())
            .limit(min(max(limit * 20, 200), 2000))
        )
        candidate_result = await session.execute(lexical_query)
        candidates = list(candidate_result.scalars().all())
    lexical_scores = {
        memory.id: score
        for memory in candidates
        if (score := _lexical_similarity(query_tokens, memory)) >= min_source_score
    }

    ranked: list[RankedMemory] = []
    candidates_by_id = {memory.id: memory for memory in candidates}
    for memory_id in set(vector_scores) | set(lexical_scores):
        vector_score = vector_scores.get(memory_id, (None, 0.0))[1]
        lexical_score = lexical_scores.get(memory_id, 0.0)
        memory = candidates_by_id.get(memory_id) or vector_scores[memory_id][0]
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
            "vector_count": len(vector_scores),
            "lexical_candidate_count": len(candidates),
            "lexical_count": len(lexical_scores),
            "selected_count": len(selected),
        },
    )
