"""Context policy readiness gate tests."""

import uuid
from datetime import datetime, timedelta, timezone

from app.models.project_knowledge import ContextOutcome, ContextRun
from app.services.context_policy_readiness import build_context_policy_readiness


def _run(
    index: int,
    *,
    action: str = "inject",
    source_mutation: str = "none",
    effective_mode: str = "shadow",
) -> ContextRun:
    now = datetime.now(timezone.utc)
    would_exclude = [str(uuid.uuid4())] if action in {"silent", "abstain"} else []
    return ContextRun(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"context-run-{index}"),
        user_id="user",
        project_id="qzhqzh/EchoMe",
        query=f"task {index}",
        mode="local",
        token_budget=1000,
        status="completed",
        trace={
            "context_policy": {
                "schema_version": 1,
                "effective_mode": effective_mode,
                "enforced": effective_mode == "enforce",
                "decision_counts": {action: 1},
                "would_exclude": {"memories": would_exclude, "constraints": []},
                "source_mutation": source_mutation,
            }
        },
        created_at=now - timedelta(minutes=index),
    )


def _outcome(run: ContextRun, effect: str, index: int = 0) -> ContextOutcome:
    return ContextOutcome(
        id=uuid.uuid4(),
        user_id="user",
        context_run_id=run.id,
        outcome="success",
        policy_effect=effect,
        idempotency_key=f"effect-{index}",
        created_at=datetime.now(timezone.utc),
    )


def test_readiness_requires_real_shadow_evidence() -> None:
    report = build_context_policy_readiness(
        [],
        [],
        window_days=30,
        project_id=None,
    )

    assert report["status"] == "insufficient_data"
    assert report["eligible_for_canary"] is False
    assert report["auto_enforce"] is False
    assert "insufficient_shadow_runs" in report["reasons"]


def test_readiness_can_only_grant_canary_eligibility() -> None:
    runs = [_run(index, action="inject_with_warning") for index in range(20)]
    outcomes = [
        _outcome(run, "helpful" if index < 3 else "neutral", index)
        for index, run in enumerate(runs[:10])
    ]

    report = build_context_policy_readiness(
        runs,
        outcomes,
        window_days=30,
        project_id="qzhqzh/EchoMe",
    )

    assert report["status"] == "eligible_for_canary"
    assert report["eligible_for_canary"] is True
    assert report["auto_enforce"] is False
    assert report["metrics"]["evaluation_coverage"] == 0.5
    assert report["metrics"]["helpful_rate"] == 0.3


def test_harmful_policy_signal_holds_rollout() -> None:
    runs = [_run(index, action="inject_with_warning") for index in range(20)]
    outcomes = [
        _outcome(run, "harmful" if index < 2 else "helpful", index)
        for index, run in enumerate(runs[:10])
    ]

    report = build_context_policy_readiness(
        runs,
        outcomes,
        window_days=30,
        project_id=None,
    )

    assert report["status"] == "hold"
    assert "harmful_rate_above_threshold" in report["reasons"]


def test_conflicting_effects_and_source_mutation_hold_rollout() -> None:
    runs = [_run(index, action="inject_with_warning") for index in range(20)]
    runs[0].trace["context_policy"]["source_mutation"] = "unexpected"
    outcomes = [_outcome(run, "helpful", index) for index, run in enumerate(runs[:10])]
    outcomes.append(_outcome(runs[0], "harmful", 100))

    report = build_context_policy_readiness(
        runs,
        outcomes,
        window_days=30,
        project_id=None,
    )

    assert report["status"] == "hold"
    assert "conflicting_policy_effects" in report["reasons"]
    assert "source_mutation_detected" in report["reasons"]


def test_enforced_runs_are_excluded_from_shadow_gate() -> None:
    runs = [_run(1, effective_mode="enforce")]
    report = build_context_policy_readiness(
        runs,
        [],
        window_days=30,
        project_id=None,
    )

    assert report["metrics"]["observed_shadow_runs"] == 0
    assert report["metrics"]["enforced_runs_excluded"] == 1


def test_non_intervention_feedback_cannot_qualify_canary() -> None:
    runs = [_run(index, action="inject") for index in range(20)]
    outcomes = [_outcome(run, "helpful", index) for index, run in enumerate(runs[:10])]

    report = build_context_policy_readiness(
        runs,
        outcomes,
        window_days=30,
        project_id=None,
    )

    assert report["status"] == "insufficient_data"
    assert report["metrics"]["evaluated_intervention_runs"] == 0
    assert "insufficient_intervention_samples" in report["reasons"]


def test_truncated_evidence_window_cannot_qualify_canary() -> None:
    runs = [_run(index, action="inject_with_warning") for index in range(20)]
    outcomes = [_outcome(run, "helpful", index) for index, run in enumerate(runs[:10])]

    report = build_context_policy_readiness(
        runs,
        outcomes,
        window_days=30,
        project_id=None,
        evidence_truncated=True,
        sample_limit=20,
    )

    assert report["status"] == "hold"
    assert report["eligible_for_canary"] is False
    assert "evidence_window_truncated" in report["reasons"]


def test_truncated_insufficient_window_is_still_a_hold() -> None:
    report = build_context_policy_readiness(
        [_run(1, action="inject_with_warning")],
        [],
        window_days=30,
        project_id=None,
        evidence_truncated=True,
        sample_limit=1,
    )

    assert report["status"] == "hold"
    assert report["reasons"][0] == "evidence_window_truncated"
    assert "insufficient_shadow_runs" in report["reasons"]


def test_malformed_policy_trace_is_not_scorable() -> None:
    run = _run(1)
    run.trace["context_policy"]["decision_counts"] = "invalid"
    run.trace["context_policy"]["would_exclude"] = ["invalid"]

    report = build_context_policy_readiness(
        [run],
        [_outcome(run, "helpful")],
        window_days=30,
        project_id=None,
    )

    assert report["status"] == "hold"
    assert report["metrics"]["intervention_runs"] == 0
    assert report["metrics"]["would_exclude_items"] == 0
    assert report["metrics"]["invalid_policy_trace_runs"] == 1
    assert "invalid_policy_trace_detected" in report["reasons"]


def test_unrounded_harmful_rate_holds_rollout() -> None:
    runs = [_run(index, action="inject_with_warning") for index in range(3)]
    outcomes = [
        _outcome(run, "harmful" if index == 0 else "helpful", index)
        for index, run in enumerate(runs)
    ]

    report = build_context_policy_readiness(
        runs,
        outcomes,
        window_days=30,
        project_id=None,
        thresholds={
            "min_shadow_runs": 3,
            "min_evaluated_intervention_runs": 3,
            "min_intervention_runs": 3,
            "min_evaluation_coverage": 1.0,
            "min_helpful_rate": 0.0,
            "max_harmful_rate": 0.3333,
        },
    )

    assert report["metrics"]["harmful_rate"] == 0.3333
    assert report["status"] == "hold"
    assert "harmful_rate_above_threshold" in report["reasons"]
