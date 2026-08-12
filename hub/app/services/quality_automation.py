"""Quality gates for proposal-only project knowledge automation."""

from __future__ import annotations

from typing import Any

QUALITY_THRESHOLDS = {
    "recall_at_10": ("min", 0.90),
    "evidence_precision": ("min", 0.90),
    "stale_answer_rate": ("max", 0.05),
    "conflict_surfacing_rate": ("min", 0.80),
    "abstention_accuracy": ("min", 0.80),
    "constraint_adherence": ("min", 0.95),
    "impact_coverage": ("min", 0.80),
    "preflight_precision": ("min", 0.80),
    "preflight_recall": ("min", 0.80),
}


def evaluate_automation_gate(
    snapshots: list[Any],
    *,
    required_snapshots: int = 3,
) -> dict[str, Any]:
    """Require consecutive snapshots to satisfy every behavior quality threshold."""
    considered = snapshots[:required_snapshots]
    failures: list[dict[str, Any]] = []
    if len(considered) < required_snapshots:
        failures.append(
            {
                "reason": "insufficient_snapshots",
                "required": required_snapshots,
                "available": len(considered),
            }
        )
    schema_versions = {item.dataset_schema_version for item in considered}
    if len(schema_versions) > 1:
        failures.append({"reason": "mixed_dataset_versions"})
    for snapshot in considered:
        if not snapshot.passed:
            failures.append({"snapshot_id": str(snapshot.id), "reason": "snapshot_recall_failed"})
        for metric, (comparison, threshold) in QUALITY_THRESHOLDS.items():
            value = snapshot.metrics.get(metric)
            metric_failed = (
                value is None
                or (comparison == "min" and value < threshold)
                or (comparison == "max" and value > threshold)
            )
            if metric_failed:
                failures.append(
                    {
                        "snapshot_id": str(snapshot.id),
                        "reason": "metric_threshold_failed",
                        "metric": metric,
                        "value": value,
                        "comparison": comparison,
                        "threshold": threshold,
                    }
                )
    return {
        "eligible": not failures,
        "required_snapshots": required_snapshots,
        "snapshot_ids": [str(item.id) for item in considered],
        "dataset_schema_version": next(iter(schema_versions), None),
        "thresholds": {
            metric: {"comparison": comparison, "value": threshold}
            for metric, (comparison, threshold) in QUALITY_THRESHOLDS.items()
        },
        "failures": failures,
    }
