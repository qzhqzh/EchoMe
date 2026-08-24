"""Read-only comparison helpers for replaying recorded retrieval queries."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any


def _result_ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item["id"]) for item in items if item.get("id")]


def _expected_rank(items: list[dict[str, Any]], expected_ids: list[str]) -> int | None:
    expected = set(expected_ids)
    for index, memory_id in enumerate(_result_ids(items), 1):
        if memory_id in expected:
            return index
    return None


def compare_retrieval_replay(
    *,
    log_id: str,
    query: str,
    expected_ids: list[str],
    previous_expected_rank: int | None,
    previous_results: list[dict[str, Any]],
    current_results: list[dict[str, Any]],
    current_trace: dict[str, Any],
    comparable: bool = True,
) -> dict[str, Any]:
    """Compare one replay with its recorded ranking without mutating the log."""
    current_expected_rank = _expected_rank(current_results, expected_ids)
    if not comparable or not expected_ids:
        outcome = "unscored"
    elif previous_expected_rank is None and current_expected_rank is not None:
        outcome = "improved"
    elif previous_expected_rank is not None and current_expected_rank is None:
        outcome = "regressed"
    elif previous_expected_rank is None or current_expected_rank is None:
        outcome = "unchanged"
    elif current_expected_rank < previous_expected_rank:
        outcome = "improved"
    elif current_expected_rank > previous_expected_rank:
        outcome = "regressed"
    else:
        outcome = "unchanged"

    previous_ids = set(_result_ids(previous_results))
    current_ids = set(_result_ids(current_results))
    union = previous_ids | current_ids
    return {
        "log_id": log_id,
        "query": query,
        "outcome": outcome,
        "expected_ids": expected_ids,
        "previous_expected_rank": previous_expected_rank,
        "current_expected_rank": current_expected_rank,
        "top_k_jaccard": round(len(previous_ids & current_ids) / len(union), 4) if union else 1.0,
        "previous_result_ids": _result_ids(previous_results),
        "current_results": current_results,
        "current_trace": current_trace,
    }


def build_replay_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate deterministic regression signals across replayed logs."""
    counts = {
        outcome: sum(item["outcome"] == outcome for item in items)
        for outcome in ("regressed", "improved", "unchanged", "unscored")
    }
    scored_count = len(items) - counts["unscored"]
    overlaps = [float(item["top_k_jaccard"]) for item in items]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "log_count": len(items),
        "scored_count": scored_count,
        **counts,
        "average_top_k_jaccard": round(mean(overlaps), 4) if overlaps else None,
        "passed": scored_count > 0 and counts["regressed"] == 0,
        "items": items,
    }
