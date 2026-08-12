"""Deterministic metrics for project context and preflight quality snapshots."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

DEFAULT_CASES_PATH = Path(__file__).resolve().parent.parent / "evals" / "context_quality_cases.json"


def load_context_quality_cases(path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    """Load and minimally validate the versioned fixed evaluation dataset."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported context quality case schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 20:
        raise ValueError("Context quality dataset must contain at least 20 cases")
    ids = [item.get("id") for item in cases]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("Context quality case IDs must be non-empty and unique")
    return payload


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(interpolated, 3)


def _path(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    locator = value.get("locator")
    if isinstance(locator, dict) and locator.get("logical_path"):
        return str(locator["logical_path"])
    if value.get("logical_path"):
        return str(value["logical_path"])
    return None


def _ranked_titles(context: dict[str, Any], limit: int) -> list[str]:
    return [
        str(item.get("title"))
        for item in context.get("constraints", [])[:limit]
        if isinstance(item, dict) and item.get("title")
    ]


def _ranked_paths(context: dict[str, Any], limit: int) -> list[str]:
    paths: list[str] = []
    for key in ("evidence", "artifacts"):
        for item in context.get(key, []):
            path = _path(item)
            if path and path not in paths:
                paths.append(path)
            if len(paths) >= limit:
                return paths
    return paths


def _statuses(context: dict[str, Any]) -> list[str]:
    values = []
    for key in ("constraints", "memories"):
        values.extend(
            str(item["status"])
            for item in context.get(key, [])
            if isinstance(item, dict) and item.get("status")
        )
    return values


def _case_retrieval(
    case: dict[str, Any],
    result: dict[str, Any],
    *,
    k: int,
) -> dict[str, Any]:
    expected = case.get("expected", {})
    context = result.get("context") or {}
    preflight = result.get("preflight") or {}
    titles = _ranked_titles(context, k)
    if case.get("mode") == "preflight":
        titles = [
            str(item.get("title"))
            for item in preflight.get("requirements", [])[:k]
            if isinstance(item, dict) and item.get("title")
        ]
    paths = _ranked_paths(context, k)
    expected_titles = list(expected.get("constraint_titles", []))
    expected_paths = list(expected.get("artifact_paths", []))
    expected_items = [("title", item) for item in expected_titles] + [
        ("path", item) for item in expected_paths
    ]
    hits = 0
    reciprocal_ranks: list[float] = []
    for kind, item in expected_items:
        ranked = titles if kind == "title" else paths
        if item in ranked:
            hits += 1
            reciprocal_ranks.append(1.0 / (ranked.index(item) + 1))
    return {
        "expected": len(expected_items),
        "hits": hits,
        "reciprocal_rank": max(reciprocal_ranks, default=0.0),
        "titles": titles,
        "paths": paths,
    }


def evaluate_context_quality(
    cases_payload: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    k: int = 10,
) -> dict[str, Any]:
    """Evaluate externally collected context/preflight outputs without database access."""
    cases = cases_payload.get("cases", [])
    case_by_id = {item["id"]: item for item in cases}
    result_by_id = {item.get("case_id"): item for item in results}
    unknown_results = sorted(set(result_by_id) - set(case_by_id))

    total_expected = 0
    total_hits = 0
    reciprocal_ranks: list[float] = []
    evidence_selected = 0
    evidence_relevant = 0
    stale_total = 0
    stale_failures = 0
    conflict_total = 0
    conflicts_surfaced = 0
    abstention_total = 0
    abstentions_correct = 0
    adherence_total = 0
    adherence_passed = 0
    impact_expected = 0
    impact_hits = 0
    preflight_warning_total = 0
    preflight_warning_supported = 0
    preflight_expected = 0
    preflight_hits = 0
    latency_values: list[float] = []
    token_values: list[float] = []
    sleep_total = 0
    sleep_accepted = 0
    case_reports: list[dict[str, Any]] = []

    for case in cases:
        result = result_by_id.get(case["id"])
        if result is None:
            case_reports.append({"case_id": case["id"], "status": "missing"})
            continue
        retrieval = _case_retrieval(case, result, k=k)
        total_expected += retrieval["expected"]
        total_hits += retrieval["hits"]
        if retrieval["expected"]:
            reciprocal_ranks.append(retrieval["reciprocal_rank"])

        context = result.get("context") or {}
        preflight = result.get("preflight") or {}
        expected = case.get("expected", {})
        selected_constraint_ids = {
            str(item.get("id"))
            for item in context.get("constraints", [])
            if isinstance(item, dict) and item.get("id")
        }
        for item in context.get("evidence", []):
            if not isinstance(item, dict):
                continue
            evidence_selected += 1
            has_locator = bool(_path(item))
            linked_to_selected = (
                item.get("evidence_type") == "artifact_chunk"
                or not item.get("constraint_id")
                or str(item.get("constraint_id")) in selected_constraint_ids
            )
            if has_locator and item.get("artifact_id") and linked_to_selected:
                evidence_relevant += 1

        if expected.get("require_stale_warning"):
            stale_total += 1
            if not context.get("stale_warnings"):
                stale_failures += 1
        if expected.get("require_conflict"):
            conflict_total += 1
            if context.get("conflicts"):
                conflicts_surfaced += 1
        if expected.get("require_abstention"):
            abstention_total += 1
            if context.get("unknowns") and not context.get("must_include"):
                abstentions_correct += 1

        statuses = _statuses(context)
        constraint_statuses = [
            str(item["status"])
            for item in context.get("constraints", [])
            if isinstance(item, dict) and item.get("status")
        ]
        forbidden = set(expected.get("forbidden_statuses", []))
        allowed = set(expected.get("allowed_statuses", []))
        if forbidden or allowed:
            adherence_total += 1
            if not (forbidden & set(statuses)) and (
                not allowed or set(constraint_statuses) <= allowed
            ):
                adherence_passed += 1

        if case.get("mode") == "impact":
            expected_titles = set(expected.get("constraint_titles", []))
            impact_expected += len(expected_titles)
            impact_hits += len(expected_titles & set(retrieval["titles"]))

        if case.get("mode") == "preflight":
            warnings = preflight.get("warnings", [])
            preflight_warning_total += len(warnings)
            preflight_warning_supported += sum(
                bool(item.get("evidence")) for item in warnings if isinstance(item, dict)
            )
            expected_event_types = set(expected.get("preflight_event_types", []))
            actual_event_types = {
                item.get("event", {}).get("event_type")
                for item in warnings
                if isinstance(item, dict) and isinstance(item.get("event"), dict)
            }
            actual_event_types.update(
                item.get("event_type")
                for item in preflight.get("events", [])
                if isinstance(item, dict)
            )
            preflight_expected += len(expected_event_types)
            preflight_hits += len(expected_event_types & actual_event_types)

        if isinstance(result.get("latency_ms"), (int, float)):
            latency_values.append(float(result["latency_ms"]))
        token_used = result.get("token_used", context.get("token_used"))
        if isinstance(token_used, (int, float)):
            token_values.append(float(token_used))
        sleep_signal = result.get("sleep_proposal")
        if isinstance(sleep_signal, dict) and "accepted" in sleep_signal:
            sleep_total += 1
            sleep_accepted += bool(sleep_signal["accepted"])

        case_reports.append(
            {
                "case_id": case["id"],
                "status": "evaluated",
                "expected_items": retrieval["expected"],
                "hits_at_k": retrieval["hits"],
                "reciprocal_rank": round(retrieval["reciprocal_rank"], 4),
            }
        )

    evaluated_count = sum(item["status"] == "evaluated" for item in case_reports)
    metrics = {
        f"recall_at_{k}": _ratio(total_hits, total_expected),
        "mrr": round(mean(reciprocal_ranks), 4) if reciprocal_ranks else None,
        "evidence_precision": _ratio(evidence_relevant, evidence_selected),
        "stale_answer_rate": _ratio(stale_failures, stale_total),
        "conflict_surfacing_rate": _ratio(conflicts_surfaced, conflict_total),
        "abstention_accuracy": _ratio(abstentions_correct, abstention_total),
        "constraint_adherence": _ratio(adherence_passed, adherence_total),
        "impact_coverage": _ratio(impact_hits, impact_expected),
        "preflight_precision": _ratio(preflight_warning_supported, preflight_warning_total),
        "preflight_recall": _ratio(preflight_hits, preflight_expected),
        "latency_p50_ms": _percentile(latency_values, 0.50),
        "latency_p95_ms": _percentile(latency_values, 0.95),
        "average_token_cost": round(mean(token_values), 3) if token_values else None,
        "sleep_proposal_acceptance_rate": _ratio(sleep_accepted, sleep_total),
    }
    recall = metrics[f"recall_at_{k}"]
    return {
        "schema_version": cases_payload.get("schema_version"),
        "project_id": cases_payload.get("project_id"),
        "case_count": len(cases),
        "evaluated_count": evaluated_count,
        "missing_case_ids": [
            item["case_id"] for item in case_reports if item["status"] == "missing"
        ],
        "unknown_result_ids": unknown_results,
        "metrics": metrics,
        "thresholds": {f"recall_at_{k}": 0.90},
        "passed": evaluated_count == len(cases) and recall is not None and recall >= 0.90,
        "cases": case_reports,
    }
