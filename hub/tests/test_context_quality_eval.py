"""Tests for the fixed Project Context quality evaluation suite."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.project_knowledge import ContextQualitySnapshotCreate
from app.services.context_quality_eval import (
    evaluate_context_quality,
    evaluate_scale_reliability,
    load_context_quality_cases,
)


def test_quality_snapshot_rejects_client_supplied_results() -> None:
    with pytest.raises(ValidationError):
        ContextQualitySnapshotCreate(
            project_id="qzhqzh/EchoMe",
            idempotency_key="forged-snapshot",
            results=[],
        )


def _perfect_result(case: dict, index: int) -> dict:
    expected = case.get("expected", {})
    constraints = [
        {"title": title, "status": "active"} for title in expected.get("constraint_titles", [])
    ]
    evidence = [
        {
            "id": f"evidence-{index}-{item_index}",
            "evidence_type": "artifact_chunk",
            "artifact_id": f"artifact-{index}-{item_index}",
            "locator": {"logical_path": path},
        }
        for item_index, path in enumerate(expected.get("artifact_paths", []))
    ]
    context = {
        "constraints": constraints,
        "memories": [],
        "artifacts": [],
        "evidence": evidence,
        "must_include": constraints,
        "unknowns": [],
        "conflicts": [],
        "stale_warnings": [],
        "token_used": 500 + index,
    }
    if expected.get("require_stale_warning"):
        context["stale_warnings"] = [{"type": "evidence_revision_changed"}]
    if expected.get("require_conflict"):
        context["conflicts"] = [{"edge_id": "conflict"}]
    if expected.get("require_abstention"):
        context["unknowns"] = ["No supported evidence matched."]
        context["must_include"] = []
    warnings = [
        {
            "event": {"event_type": event_type},
            "evidence": [{"type": "artifact", "id": f"artifact-{index}"}],
        }
        for event_type in expected.get("preflight_event_types", [])
    ]
    preflight = {
        "requirements": constraints,
        "warnings": warnings,
        "events": [
            {
                "event_type": event_type,
                "evidence": [{"type": "artifact", "id": f"artifact-{index}"}],
            }
            for event_type in expected.get("preflight_event_types", [])
        ],
        "unknowns": [],
    }
    return {
        "case_id": case["id"],
        "context": context,
        "preflight": preflight,
        "latency_ms": 10 + index,
        "token_used": 500 + index,
    }


def test_fixed_dataset_has_required_coverage() -> None:
    payload = load_context_quality_cases()

    categories = {item["category"] for item in payload["cases"]}
    abilities = {item["ability"] for item in payload["cases"]}
    assert payload["schema_version"] == 2
    assert len(payload["cases"]) >= 30
    assert abilities == {
        "static_state_recall",
        "dynamic_state_tracking",
        "workflow_knowledge",
        "environment_gotchas",
        "premise_awareness",
    }
    assert {
        "single_fact",
        "cross_source_reasoning",
        "temporal_state",
        "supersession",
        "conflict",
        "abstention",
        "implicit_constraint",
        "workflow_failure",
        "changed_path_impact",
        "inactive_exclusion",
    } <= categories


def test_perfect_snapshot_passes_recall_and_reports_all_metrics() -> None:
    payload = load_context_quality_cases()
    results = [_perfect_result(case, index) for index, case in enumerate(payload["cases"])]

    report = evaluate_context_quality(payload, results)

    assert report["evaluated_count"] == len(payload["cases"])
    assert report["metrics"]["recall_at_10"] == 1.0
    assert report["metrics"]["mrr"] == 1.0
    assert report["metrics"]["evidence_precision"] == 1.0
    assert report["metrics"]["stale_answer_rate"] == 0.0
    assert report["metrics"]["conflict_surfacing_rate"] == 1.0
    assert report["metrics"]["abstention_accuracy"] == 1.0
    assert report["metrics"]["constraint_adherence"] == 1.0
    assert report["metrics"]["impact_coverage"] == 1.0
    assert report["metrics"]["preflight_precision"] == 1.0
    assert report["metrics"]["preflight_recall"] == 1.0
    assert report["metrics"]["case_success_rate"] == 1.0
    assert report["metrics"]["sensitive_path_leak_rate"] == 0.0
    assert set(report["ability_metrics"]) == {
        "static_state_recall",
        "dynamic_state_tracking",
        "workflow_knowledge",
        "environment_gotchas",
        "premise_awareness",
    }
    assert all(
        item["case_success_rate"] == 1.0
        for item in report["ability_metrics"].values()
    )
    assert report["metrics"]["latency_p95_ms"] is not None
    assert report["metrics"]["average_token_cost"] is not None
    assert report["metrics"]["sleep_proposal_acceptance_rate"] is None
    assert report["passed"] is True


def test_missing_and_stale_failure_do_not_pass() -> None:
    payload = load_context_quality_cases()
    stale_case = next(
        item for item in payload["cases"] if item.get("expected", {}).get("require_stale_warning")
    )
    result = _perfect_result(stale_case, 0)
    result["context"]["stale_warnings"] = []

    report = evaluate_context_quality(payload, [result])

    assert report["metrics"]["stale_answer_rate"] > 0.0
    assert len(report["missing_case_ids"]) == len(payload["cases"]) - 1
    assert report["passed"] is False


def test_stale_answer_fails_full_snapshot_even_with_perfect_recall() -> None:
    payload = load_context_quality_cases()
    results = [_perfect_result(case, index) for index, case in enumerate(payload["cases"])]
    stale_case = next(
        item for item in payload["cases"] if item.get("expected", {}).get("require_stale_warning")
    )
    stale_result = next(item for item in results if item["case_id"] == stale_case["id"])
    stale_result["context"]["stale_warnings"] = []

    report = evaluate_context_quality(payload, results)

    assert report["metrics"]["recall_at_10"] == 1.0
    assert report["metrics"]["stale_answer_rate"] > 0.0
    assert report["passed"] is False


def test_one_weak_ability_fails_even_when_global_metrics_still_pass() -> None:
    payload = load_context_quality_cases()
    results = [_perfect_result(case, index) for index, case in enumerate(payload["cases"])]
    case = next(
        item
        for item in payload["cases"]
        if item["ability"] == "workflow_knowledge"
        and item.get("expected", {}).get("constraint_titles")
    )
    result = next(item for item in results if item["case_id"] == case["id"])
    result["context"]["constraints"] = []

    report = evaluate_context_quality(payload, results)

    assert report["metrics"]["case_success_rate"] >= 0.90
    assert report["ability_metrics"]["workflow_knowledge"]["case_success_rate"] < 0.90
    assert report["passed"] is False


def test_sensitive_artifact_path_fails_full_snapshot() -> None:
    payload = load_context_quality_cases()
    results = [_perfect_result(case, index) for index, case in enumerate(payload["cases"])]
    protected_case = next(
        item
        for item in payload["cases"]
        if item.get("expected", {}).get("forbidden_artifact_paths")
    )
    protected_result = next(item for item in results if item["case_id"] == protected_case["id"])
    protected_result["context"]["artifacts"] = [{"logical_path": ".env"}]

    report = evaluate_context_quality(payload, results)

    assert report["metrics"]["sensitive_path_leak_rate"] == 1.0
    assert report["passed"] is False


def test_forbidden_inactive_status_fails_constraint_adherence() -> None:
    payload = load_context_quality_cases()
    case = next(
        item for item in payload["cases"] if item.get("expected", {}).get("forbidden_statuses")
    )
    result = _perfect_result(case, 0)
    result["context"]["memories"] = [{"status": case["expected"]["forbidden_statuses"][0]}]
    single_payload = deepcopy(payload)
    single_payload["cases"] = [case] * 20
    for index, item in enumerate(single_payload["cases"]):
        item = deepcopy(item)
        item["id"] = f"{case['id']}-{index}"
        single_payload["cases"][index] = item
    results = []
    for item in single_payload["cases"]:
        cloned = deepcopy(result)
        cloned["case_id"] = item["id"]
        results.append(cloned)

    report = evaluate_context_quality(single_payload, results)

    assert report["metrics"]["constraint_adherence"] == 0.0


def test_scale_reliability_reports_first_breakdown() -> None:
    observations = [
        {
            "case_id": f"small-{index}",
            "memory_count": 100,
            "irrelevant_count": 50,
            "correct": True,
            "memory_calls": 1,
            "token_used": 500,
        }
        for index in range(10)
    ]
    observations.extend(
        {
            "case_id": f"large-{index}",
            "memory_count": 10_000,
            "irrelevant_count": 9_900,
            "correct": index < 6,
            "memory_calls": 3 if index >= 5 else 2,
            "token_used": 1200,
        }
        for index in range(10)
    )

    report = evaluate_scale_reliability(observations)

    assert report["baseline_reliability"] == 1.0
    assert report["breakdown_onset"] == 10_000
    assert report["scales"][1]["budget_compliant_reliability"] == 0.5
    assert report["passed"] is False


def test_scale_gate_uses_unrounded_reliability() -> None:
    observations = [
        {
            "case_id": f"case-{index}",
            "memory_count": 100,
            "correct": index < 2,
            "memory_calls": 1,
        }
        for index in range(3)
    ]

    report = evaluate_scale_reliability(
        observations,
        reliability_threshold=0.6667,
    )

    assert report["scales"][0]["budget_compliant_reliability"] < 0.6667
    assert report["breakdown_onset"] == 100
    assert report["passed"] is False
