"""Optional, evidence-based reporting contract for recorded context runs."""

from __future__ import annotations


def completion_contract(context_run_id: str, *, shadow: bool = False) -> dict[str, object]:
    """Keep reporting available without requiring a per-task completion ritual."""
    return {
        "schema_version": "echome.context-completion.v1",
        "context_run_id": context_run_id,
        "report_outcome": False,
        "required_at_task_end": False,
        "outcome_available": not shadow,
        "tool": "echome_context_outcome",
        "idempotency_key": f"context:{context_run_id}:completion",
        "allowed_outcomes": ["success", "partial", "failed", "corrected", "no_signal"],
        "rules": [
            "Report only evidenced usefulness or corrections.",
            "Skip unknown outcomes; no_signal is optional.",
            "Task completion does not prove memory helped.",
            "Use policy_effect only with evidence. Do not request ratings.",
        ],
        "reason": (
            "Optional; skip unknown usefulness."
            if not shadow
            else "Shadow comparison runs do not accept outcomes."
        ),
    }
