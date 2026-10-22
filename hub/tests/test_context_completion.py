"""Optional outcomes retain their v1 identity and write compatibility."""

import pytest

from app.services.context_completion import completion_contract


@pytest.mark.parametrize("shadow", [False, True])
def test_outcome_contract_never_requires_a_task_end_call(shadow: bool) -> None:
    contract = completion_contract("recorded-run", shadow=shadow)

    assert contract["schema_version"] == "echome.context-completion.v1"
    assert contract["context_run_id"] == "recorded-run"
    assert contract["report_outcome"] is False
    assert contract["required_at_task_end"] is False
    assert contract["outcome_available"] is not shadow
    assert contract["tool"] == "echome_context_outcome"
    assert contract["idempotency_key"] == "context:recorded-run:completion"
    assert contract["allowed_outcomes"] == ["success", "partial", "failed", "corrected", "no_signal"]


def test_shadow_contract_still_prohibits_outcomes() -> None:
    contract = completion_contract("shadow-run", shadow=True)

    assert contract["outcome_available"] is False
    assert contract["reason"] == "Shadow comparison runs do not accept outcomes."
