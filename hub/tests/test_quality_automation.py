"""Tests for consecutive fixed-snapshot automation quality gates."""

import uuid
from types import SimpleNamespace

from app.services.quality_automation import QUALITY_THRESHOLDS, evaluate_automation_gate


def test_automation_uses_the_strict_eval_threshold_contract() -> None:
    assert QUALITY_THRESHOLDS["stale_answer_rate"] == ("max", 0.0)
    assert QUALITY_THRESHOLDS["conflict_surfacing_rate"] == ("min", 1.0)
    assert QUALITY_THRESHOLDS["case_success_rate"] == ("min", 0.9)
    assert QUALITY_THRESHOLDS["sensitive_path_leak_rate"] == ("max", 0.0)


def _snapshot(*, passed: bool = True, overrides: dict | None = None) -> SimpleNamespace:
    metrics = {
        metric: threshold if comparison == "min" else 0.0
        for metric, (comparison, threshold) in QUALITY_THRESHOLDS.items()
    }
    metrics.update(overrides or {})
    return SimpleNamespace(
        id=uuid.uuid4(),
        dataset_schema_version=1,
        passed=passed,
        metrics=metrics,
    )


def test_gate_requires_three_consecutive_passing_snapshots() -> None:
    gate = evaluate_automation_gate([_snapshot(), _snapshot(), _snapshot()])

    assert gate["eligible"] is True
    assert len(gate["snapshot_ids"]) == 3


def test_gate_rejects_missing_snapshot_or_behavior_metric_failure() -> None:
    missing = evaluate_automation_gate([_snapshot(), _snapshot()])
    failing = evaluate_automation_gate(
        [_snapshot(), _snapshot(), _snapshot(overrides={"abstention_accuracy": 0.5})]
    )

    assert missing["eligible"] is False
    assert any(item["reason"] == "insufficient_snapshots" for item in missing["failures"])
    assert failing["eligible"] is False
    assert any(item.get("metric") == "abstention_accuracy" for item in failing["failures"])
