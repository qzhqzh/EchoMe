"""Evaluation failures must not inflate accuracy or hide risky errors."""

import json
from pathlib import Path

from echome.core.memory_gate import GateRequest
from scripts.eval_memory_gate import percentile, summarize


def test_summary_counts_missing_predictions_and_dangerous_errors() -> None:
    rows = [
        {
            "phase": "read",
            "expected_actions": ["retrieve"],
            "action": "skip",
            "model_action": "skip",
            "provider": "kev",
            "latency_ms": 100,
        },
        {
            "phase": "write",
            "expected_actions": ["skip"],
            "action": "propose",
            "model_action": "propose",
            "provider": "kev",
            "latency_ms": 200,
        },
        {
            "phase": "write",
            "expected_actions": ["review"],
            "action": "review",
            "provider": "kev",
            "latency_ms": 2000,
            "degraded": True,
            "reason_code": "provider_timeout",
        },
        {
            "phase": "read",
            "expected_actions": ["retrieve"],
            "action": None,
            "provider": "kev",
            "latency_ms": 3000,
            "error": "timeout",
        },
    ]
    summary = summarize(rows)
    assert summary["accuracy"] == 0.25
    assert summary["raw_model_decisions"] == 2
    assert summary["raw_model_correct"] == 0
    assert summary["read_false_skip"] == 1
    assert summary["read_required"] == 2
    assert summary["write_false_propose"] == 1
    assert summary["write_should_not_propose"] == 2
    assert summary["degraded"] == 1
    assert summary["errors"] == {"timeout": 1, "provider_timeout": 1}
    assert summary["latency_p95_ms"] == 3000
    assert percentile([], 0.95) is None


def test_frozen_fixture_has_balanced_valid_unique_cases() -> None:
    source = Path(__file__).parent / "fixtures/memory_gate_cases.json"
    dataset = json.loads(source.read_text())
    assert dataset["synthetic"] is True
    cases = dataset["cases"]
    assert len(cases) == len({case["id"] for case in cases}) == 60
    assert sum(case["phase"] == "read" for case in cases) == 30
    for case in cases:
        GateRequest.model_validate(
            {key: case[key] for key in GateRequest.model_fields if key in case}
        )
        assert case["expected_actions"]
        assert case["split"] in {"dev", "holdout"}
        assert case["cohort"] in {"semantic", "control"}
