"""Derive a conservative rollout gate from context policy evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_knowledge import ContextOutcome, ContextRun

READINESS_SCHEMA_VERSION = "echome.context-policy-readiness.v1"
SCORABLE_POLICY_EFFECTS = {"helpful", "neutral", "harmful"}
INTERVENTION_ACTIONS = {"inject_with_warning", "expand", "silent", "abstain"}
DEFAULT_THRESHOLDS: dict[str, int | float] = {
    "min_shadow_runs": 20,
    "min_evaluated_intervention_runs": 10,
    "min_intervention_runs": 10,
    "min_evaluation_coverage": 0.5,
    "min_helpful_rate": 0.2,
    "max_harmful_rate": 0.05,
    "max_conflicting_effect_runs": 0,
    "max_source_mutation_violations": 0,
}


@dataclass(frozen=True)
class PolicyRunSignal:
    id: UUID
    trace: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class PolicyOutcomeSignal:
    context_run_id: UUID
    outcome: str
    policy_effect: str | None


PolicyRun = ContextRun | PolicyRunSignal
PolicyOutcome = ContextOutcome | PolicyOutcomeSignal


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _display_ratio(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _is_positive_count(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _is_valid_shadow_policy(policy: dict[str, Any]) -> bool:
    decision_counts = policy.get("decision_counts")
    would_exclude = policy.get("would_exclude")
    return (
        policy.get("schema_version") == 1
        and policy.get("effective_mode") == "shadow"
        and policy.get("enforced") is False
        and isinstance(decision_counts, dict)
        and all(
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for key, value in decision_counts.items()
        )
        and isinstance(would_exclude, dict)
        and all(
            isinstance(would_exclude.get(key), list)
            and all(isinstance(item, str) for item in would_exclude[key])
            for key in ("memories", "constraints")
        )
        and isinstance(policy.get("source_mutation"), str)
    )


def _aggregate_policy_effect(items: Sequence[PolicyOutcome]) -> str | None:
    effects = {
        item.policy_effect for item in items if item.policy_effect in SCORABLE_POLICY_EFFECTS
    }
    if "harmful" in effects and "helpful" in effects:
        return "conflicting"
    if "harmful" in effects:
        return "harmful"
    if "helpful" in effects:
        return "helpful"
    if "neutral" in effects:
        return "neutral"
    return None


def _aggregate_outcome(items: Sequence[PolicyOutcome]) -> str | None:
    values = {item.outcome for item in items}
    for value in ("corrected", "failed", "partial", "success", "no_signal"):
        if value in values:
            return value
    return None


def build_context_policy_readiness(
    runs: Sequence[PolicyRun],
    outcomes: Sequence[PolicyOutcome],
    *,
    window_days: int,
    project_id: str | None,
    now: datetime | None = None,
    thresholds: dict[str, int | float] | None = None,
    evidence_truncated: bool = False,
    sample_limit: int | None = None,
) -> dict[str, Any]:
    """Build one deterministic, non-activating readiness report."""
    effective_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    generated_at = now or datetime.now(timezone.utc)
    shadow_runs: list[tuple[PolicyRun, dict[str, Any]]] = []
    enforced_run_count = 0
    ignored_run_count = 0
    invalid_policy_trace_count = 0
    for run in runs:
        policy = run.trace.get("context_policy") if isinstance(run.trace, dict) else None
        if not isinstance(policy, dict):
            ignored_run_count += 1
            continue
        effective_mode = policy.get("effective_mode")
        if effective_mode == "enforce":
            enforced_run_count += 1
            continue
        if effective_mode == "off":
            ignored_run_count += 1
            continue
        if effective_mode != "shadow" or not _is_valid_shadow_policy(policy):
            invalid_policy_trace_count += 1
            ignored_run_count += 1
            continue
        shadow_runs.append((run, policy))

    outcomes_by_run: dict[UUID, list[PolicyOutcome]] = defaultdict(list)
    shadow_run_ids = {run.id for run, _ in shadow_runs}
    for item in outcomes:
        if item.context_run_id in shadow_run_ids:
            outcomes_by_run[item.context_run_id].append(item)

    policy_effects: dict[str, int] = defaultdict(int)
    task_outcomes: dict[str, int] = defaultdict(int)
    outcome_run_count = 0
    evaluated_intervention_run_count = 0
    intervention_run_count = 0
    would_exclude_run_count = 0
    would_exclude_item_count = 0
    source_mutation_violations = 0
    for run, policy in shadow_runs:
        raw_decision_counts = policy.get("decision_counts")
        decision_counts = raw_decision_counts if isinstance(raw_decision_counts, dict) else {}
        is_intervention = any(
            _is_positive_count(decision_counts.get(action)) for action in INTERVENTION_ACTIONS
        )
        if is_intervention:
            intervention_run_count += 1
        raw_would_exclude = policy.get("would_exclude")
        would_exclude = raw_would_exclude if isinstance(raw_would_exclude, dict) else {}
        excluded_count = sum(
            len(value) for value in would_exclude.values() if isinstance(value, list)
        )
        if excluded_count:
            would_exclude_run_count += 1
            would_exclude_item_count += excluded_count
        if policy.get("source_mutation", "none") != "none":
            source_mutation_violations += 1

        run_outcomes = outcomes_by_run.get(run.id, [])
        if run_outcomes:
            outcome_run_count += 1
        task_outcome = _aggregate_outcome(run_outcomes)
        if task_outcome:
            task_outcomes[task_outcome] += 1
        effect = _aggregate_policy_effect(run_outcomes)
        if effect and is_intervention:
            evaluated_intervention_run_count += 1
            policy_effects[effect] += 1

    observed_run_count = len(shadow_runs)
    helpful_count = policy_effects["helpful"]
    harmful_count = policy_effects["harmful"]
    conflicting_count = policy_effects["conflicting"]
    evaluation_coverage = _ratio(
        evaluated_intervention_run_count,
        intervention_run_count,
    )
    helpful_rate = _ratio(helpful_count, evaluated_intervention_run_count)
    harmful_rate = _ratio(harmful_count, evaluated_intervention_run_count)

    insufficient_reasons: list[str] = []
    hold_reasons: list[str] = []
    if observed_run_count < int(effective_thresholds["min_shadow_runs"]):
        insufficient_reasons.append("insufficient_shadow_runs")
    if evaluated_intervention_run_count < int(
        effective_thresholds["min_evaluated_intervention_runs"]
    ):
        insufficient_reasons.append("insufficient_intervention_policy_effects")
    if intervention_run_count < int(effective_thresholds["min_intervention_runs"]):
        insufficient_reasons.append("insufficient_intervention_samples")
    if (evaluation_coverage or 0.0) < float(effective_thresholds["min_evaluation_coverage"]):
        insufficient_reasons.append("low_policy_effect_coverage")

    if evaluated_intervention_run_count >= int(
        effective_thresholds["min_evaluated_intervention_runs"]
    ):
        if (helpful_rate or 0.0) < float(effective_thresholds["min_helpful_rate"]):
            hold_reasons.append("helpful_rate_below_threshold")
        if (harmful_rate or 0.0) > float(effective_thresholds["max_harmful_rate"]):
            hold_reasons.append("harmful_rate_above_threshold")
    if conflicting_count > int(effective_thresholds["max_conflicting_effect_runs"]):
        hold_reasons.append("conflicting_policy_effects")
    if source_mutation_violations > int(effective_thresholds["max_source_mutation_violations"]):
        hold_reasons.append("source_mutation_detected")
    if evidence_truncated:
        hold_reasons.insert(0, "evidence_window_truncated")
    if invalid_policy_trace_count:
        hold_reasons.append("invalid_policy_trace_detected")

    if evidence_truncated or invalid_policy_trace_count:
        status = "hold"
        reasons = [*hold_reasons, *insufficient_reasons]
    elif insufficient_reasons:
        status = "insufficient_data"
        reasons = [*insufficient_reasons, *hold_reasons]
    elif hold_reasons:
        status = "hold"
        reasons = hold_reasons
    else:
        status = "eligible_for_canary"
        reasons = ["shadow_evidence_meets_canary_thresholds"]

    recommendations = {
        "insufficient_data": [
            "Keep policy_mode=shadow and collect explicit policy_effect signals.",
            "Exercise warning and would-exclude paths before reassessing.",
        ],
        "hold": [
            "Keep policy_mode=shadow and inspect harmful or conflicting examples.",
            "Adjust policy rules, then collect a fresh evidence window.",
        ],
        "eligible_for_canary": [
            "Review sampled traces before a separately approved, reversible canary.",
            "Do not enable global enforce from this report.",
        ],
    }[status]

    latest_observed_at = max(
        (run.created_at for run, _ in shadow_runs),
        default=None,
    )
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "project_id": project_id,
        "window_days": window_days,
        "sample_limit": sample_limit,
        "evidence_truncated": evidence_truncated,
        "status": status,
        "eligible_for_canary": status == "eligible_for_canary",
        "auto_enforce": False,
        "reasons": reasons,
        "recommendations": recommendations,
        "thresholds": effective_thresholds,
        "metrics": {
            "observed_shadow_runs": observed_run_count,
            "ignored_runs": ignored_run_count,
            "invalid_policy_trace_runs": invalid_policy_trace_count,
            "enforced_runs_excluded": enforced_run_count,
            "outcome_runs": outcome_run_count,
            "evaluated_intervention_runs": evaluated_intervention_run_count,
            "intervention_runs": intervention_run_count,
            "would_exclude_runs": would_exclude_run_count,
            "would_exclude_items": would_exclude_item_count,
            "evaluation_coverage": _display_ratio(evaluation_coverage),
            "helpful_rate": _display_ratio(helpful_rate),
            "harmful_rate": _display_ratio(harmful_rate),
            "source_mutation_violations": source_mutation_violations,
            "policy_effects": dict(sorted(policy_effects.items())),
            "task_outcomes": dict(sorted(task_outcomes.items())),
            "latest_observed_at": (latest_observed_at.isoformat() if latest_observed_at else None),
        },
    }


async def evaluate_context_policy_readiness(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str | None = None,
    window_days: int = 30,
    max_runs: int = 1000,
) -> dict[str, Any]:
    """Load bounded append-only evidence and derive rollout readiness."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    query = select(ContextRun.id, ContextRun.trace, ContextRun.created_at).where(
        ContextRun.user_id == user_id,
        ContextRun.status == "completed",
        ContextRun.created_at >= cutoff,
    )
    if project_id:
        query = query.where(ContextRun.project_id == project_id)
    result = await session.execute(query.order_by(ContextRun.created_at.desc()).limit(max_runs + 1))
    fetched_runs = [
        PolicyRunSignal(id=run_id, trace=trace, created_at=created_at)
        for run_id, trace, created_at in result.all()
    ]
    evidence_truncated = len(fetched_runs) > max_runs
    runs = fetched_runs[:max_runs]
    run_ids = [run.id for run in runs]
    outcomes: list[PolicyOutcomeSignal] = []
    if run_ids:
        outcome_result = await session.execute(
            select(
                ContextOutcome.context_run_id,
                ContextOutcome.outcome,
                ContextOutcome.policy_effect,
            )
            .where(
                ContextOutcome.user_id == user_id,
                ContextOutcome.context_run_id.in_(run_ids),
            )
            .distinct()
        )
        outcomes = [
            PolicyOutcomeSignal(
                context_run_id=context_run_id,
                outcome=outcome,
                policy_effect=policy_effect,
            )
            for context_run_id, outcome, policy_effect in outcome_result.all()
        ]
    return build_context_policy_readiness(
        runs,
        outcomes,
        window_days=window_days,
        project_id=project_id,
        now=now,
        evidence_truncated=evidence_truncated,
        sample_limit=max_runs,
    )
