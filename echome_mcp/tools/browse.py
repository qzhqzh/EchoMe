"""echome_search_summary - Browse compact memory index entries."""

import re

from echome_mcp.hub_client import MCPHubClient


def _summarize(content: str, max_chars: int = 160) -> str:
    """Return a compact one-line summary from memory content."""
    summary = " ".join(content.split())
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 3] + "..."


def _query_tokens(query: str | None) -> list[str]:
    if not query:
        return []
    tokens = re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", query.lower())
    stop_tokens = {"我的", "怎样", "怎么", "什么", "如何", "规则", "the", "and", "for"}
    filtered = [token for token in tokens if len(token) >= 2 and token not in stop_tokens]
    expanded = list(filtered)
    expansions = {
        "提交": ["commit", "pr"],
        "提交流程": ["commit", "pr", "workflow"],
        "流程": ["workflow"],
        "规范": ["rule", "workflow"],
        "家庭网络": ["网络", "edgeone", "wireguard", "nginx"],
        "网络架构": ["网络", "edgeone", "wireguard", "nginx"],
    }
    query_lower = query.lower()
    for phrase, extra_tokens in expansions.items():
        if phrase in query_lower:
            expanded.extend(extra_tokens)
    return list(dict.fromkeys(expanded))[:12]


def _client_relevance(item: dict, tokens: list[str]) -> int:
    if not tokens:
        return 0
    title = str(item.get("title", "")).lower()
    tags = " ".join(str(tag) for tag in item.get("tags", [])).lower()
    content = str(item.get("content", "")).lower()
    score = 0
    for token in tokens:
        if _contains_token(title, token):
            score += 5
        if _contains_token(tags, token):
            score += 4
        if _contains_token(content, token):
            score += 1
    return score


def _contains_token(text: str, token: str) -> bool:
    if re.fullmatch(r"[a-z0-9_+#.-]+", token):
        if token == "git":
            return re.search(r"\bgit(?:hub)?\b", text) is not None
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


async def echome_search_summary(
    type: str | None = None,  # noqa: A002
    status: str = "active",
    project_id: str | None = None,
    query: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> str:
    """Browse memory index entries without loading full search results."""
    client = MCPHubClient()
    requested_limit = limit
    fetch_limit = min(max(limit * 4, limit), 50) if query and offset == 0 else limit

    try:
        result = await client.browse_memories(
            memory_type=type,
            status=status,
            project_id=project_id,
            query=query,
            limit=fetch_limit,
            offset=offset,
        )
    except Exception as e:
        return f"Error browsing memories: {e}"

    items = result.get("items", [])
    total = result.get("total", len(items))
    fallback_note = ""
    lightweight_count = len(items)
    semantic_count = 0
    fallback_used = False
    if not items and query and offset == 0:
        try:
            fallback = await client.search(
                query=query,
                memory_type=type,
                project_id=project_id,
                top_k=fetch_limit,
            )
            items = fallback.get("results", [])
            total = len(items)
            semantic_count = len(items)
            fallback_used = True
            fallback_note = (
                "Lightweight summary filters found no exact matches, so this used semantic search fallback."
            )
        except Exception as e:
            return f"Error browsing memories: {e}"

    if not items:
        return "No memories found for these filters."
    tokens = _query_tokens(query)
    if tokens:
        items = sorted(
            items,
            key=lambda item: (
                _client_relevance(item, tokens),
                item.get("priority") or 0,
                item.get("score") or 0,
                item.get("updated_at") or "",
            ),
            reverse=True,
        )
    items = items[:requested_limit]
    if query and offset == 0:
        await _record_retrieval_log(
            client=client,
            query=query,
            status=status,
            project_id=project_id,
            limit=requested_limit,
            lightweight_count=lightweight_count,
            semantic_count=semantic_count,
            fallback_used=fallback_used,
            items=items,
            tokens=tokens,
        )

    output_parts = [
        f"## Memory Search Summary ({len(items)} shown / {total} total)",
        "",
        "Pick the numbered entries that matter, then call `echome_get_memories(memory_ids=[...])` with their UUIDs for full content.",
        "",
    ]
    if fallback_note:
        output_parts.extend([f"Note: {fallback_note}", ""])

    for index, item in enumerate(items, offset + 1):
        mem_id = str(item.get("id", ""))
        title = item.get("title", "Untitled")
        mem_type = item.get("type", "")
        layer = item.get("layer", "")
        priority = item.get("priority")
        score = item.get("score")
        tags = ", ".join(item.get("tags", []))
        updated_at = item.get("updated_at", "")
        content = item.get("content", "")
        summary = _summarize(content) if content else ""

        output_parts.append(f"{index}. `{mem_id}` **{title}**")
        meta_parts = [f"Type: {mem_type}"]
        if layer:
            meta_parts.append(f"Layer: {layer}")
        if priority is not None:
            meta_parts.append(f"P{priority}")
        if score is not None:
            meta_parts.append(f"Score: {score:.2f}")
        if updated_at:
            meta_parts.append(f"Updated: {updated_at}")
        output_parts.append("   " + " | ".join(meta_parts))
        if tags:
            output_parts.append(f"   Tags: {tags}")
        if summary:
            output_parts.append(f"   Summary: {summary}")

    next_offset = offset + len(items)
    if next_offset < total:
        output_parts.append("")
        output_parts.append(f"More results available: call again with `offset={next_offset}`.")

    return "\n".join(output_parts)


async def _record_retrieval_log(
    client: MCPHubClient,
    query: str,
    status: str,
    project_id: str | None,
    limit: int,
    lightweight_count: int,
    semantic_count: int,
    fallback_used: bool,
    items: list[dict],
    tokens: list[str],
) -> None:
    top_results = [
        {
            "id": str(item.get("id", "")),
            "title": item.get("title", ""),
            "type": item.get("type", ""),
            "layer": item.get("layer", ""),
            "tags": item.get("tags", []),
            "score": item.get("score"),
        }
        for item in items
    ]
    try:
        await client.create_retrieval_log(
            {
                "query": query,
                "client": "mcp",
                "source": "echome_search_summary",
                "status": status,
                "project_id": project_id,
                "limit": limit,
                "lightweight_count": lightweight_count,
                "semantic_count": semantic_count,
                "fallback_used": fallback_used,
                "top_results": top_results,
                "steps": [
                    {"stage": "lightweight", "count": lightweight_count, "tokens": tokens},
                    {"stage": "semantic_fallback", "count": semantic_count, "used": fallback_used},
                ],
            }
        )
    except Exception:
        return


async def echome_browse_memories(
    type: str | None = None,  # noqa: A002
    status: str = "active",
    project_id: str | None = None,
    query: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> str:
    """Backward-compatible alias for echome_search_summary."""
    return await echome_search_summary(
        type=type,
        status=status,
        project_id=project_id,
        query=query,
        limit=limit,
        offset=offset,
    )
