"""Stable post-task reporting contract for recorded context runs."""

from __future__ import annotations


def completion_contract(context_run_id: str, *, shadow: bool = False) -> dict[str, object]:
    """Tell clients exactly how to close a delivered context run."""
    return {
        "schema_version": "echome.context-completion.v1",
        "context_run_id": context_run_id,
        "report_outcome": not shadow,
        "required_at_task_end": not shadow,
        "tool": "echome_context_outcome",
        "idempotency_key": f"context:{context_run_id}:completion",
        "allowed_outcomes": ["success", "partial", "failed", "corrected", "no_signal"],
        "rules": [
            "Use success, partial, failed, or corrected only when task evidence exists.",
            "Use no_signal when the task completed but context usefulness cannot be judged.",
            "Report policy_effect only when the observed intervention clearly helped or harmed.",
            "Do not ask the user for a rating unless they are already correcting the result.",
        ],
        "reason": None if not shadow else "Shadow comparison runs do not accept outcomes.",
    }
