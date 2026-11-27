"""Complete-output budgets must retain rules or return an explicit failure."""

import json
from copy import deepcopy

import pytest

from app.services.context_completion import completion_contract
from app.services.context_output import OUTPUT_BUDGET_NOTICE, context_output, measure_output


@pytest.mark.parametrize("content", ["abc " * 4000, "中文记忆。" * 4000])
def test_compact_budget_preserves_rules_conflicts_and_completion(content):
    original = {
        "schema_version": "echome.context.v1",
        "answerability": "conflicted",
        "memories": [
            {"id": "rule", "type": "guardrail", "content": "Preserve data."},
            {"id": "optional", "type": "context", "content": content},
        ],
        "constraints": [{"id": "constraint", "statement": "Verify evidence."}],
        "conflicts": [{"source_constraint_id": "constraint", "reason": "Unresolved."}],
        "unknowns": ["Deployment status is unknown."],
        "retrieval_trace": {"large": content},
        "preflight": {"large": content},
        "context_run_id": "run",
        "completion_contract": completion_contract("run"),
    }
    full = context_output(original)
    compact = context_output(original, mode="compact", limit=2200)
    assert full["preflight"] == original["preflight"]
    assert compact["memories"] == original["memories"][:1]
    assert compact["conflicts"] == original["conflicts"]
    assert compact["constraints"] == original["constraints"]
    assert compact["completion_contract"] == original["completion_contract"]
    assert compact["answerability"] == "conflicted"
    assert compact["output_usage"]["tokens_upper_bound"] == measure_output(compact) <= 2200
    assert len(original["memories"]) == 2
    assert "retrieval_trace" in original


def test_low_budget_is_explicit_and_bounded():
    output = context_output(
        {
            "memories": [{"id": "rule", "type": "guardrail", "content": "Rule " * 2000}],
        },
        mode="compact",
        limit=256,
    )
    assert output["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    assert output["output_usage"]["tokens_upper_bound"] == measure_output(output) <= 256
    assert "Rule" not in json.dumps(output)


def test_oversized_optional_reference_does_not_fail_complete_mandatory_envelope():
    rule = {"id": "rule", "type": "guardrail", "content": "Preserve existing data."}
    output = context_output(
        {
            "memories": [
                rule,
                {"id": "optional", "title": "Large title " * 500, "content": "Detail " * 1000},
            ],
            "answerability": "supported",
        },
        mode="compact",
        limit=1000,
    )

    assert "error" not in output
    assert output["memories"] == [rule]
    assert "memory_index" not in output
    assert output["omitted_counts"] == {"memories": 1}
    assert output["answerability"] == "partial"
    assert OUTPUT_BUDGET_NOTICE in output["unknowns"]
    assert measure_output(output) <= 1000


def test_compact_preflight_reuses_complete_constraints_without_repeated_diagnostics() -> None:
    constraint = {
        "id": "data-rule",
        "version": 3,
        "statement": "Preserve the customer database, including archived records. " * 20,
        "kind": "security",
        "status": "active",
        "reliability": {"evidence": "Detailed evidence " * 1000},
        "selection_reasons": ["lexical:rank_1"],
        "intervention": {"action": "inject", "reason": "support_state:current_supported"},
    }
    source = {
        "schema_version": "echome.context.v1",
        "constraints": [constraint],
        "preflight": {
            "decision": "proceed",
            "requirements": [{**deepcopy(constraint), "selection_reasons": ["invariant"]}],
            "warnings": [],
            "stale_warnings": [],
            "unknowns": [],
        },
    }
    before = deepcopy(source)

    output = context_output(source, mode="compact", limit=3000)

    requirement = output["preflight"]["requirements"][0]
    assert requirement == {
        "id": "data-rule",
        "version": 3,
        "context_ref": "#/constraints/0",
        "needs_expansion": False,
    }
    assert output["constraints"][0]["statement"] == constraint["statement"]
    assert output["constraints"][0]["intervention"] == {"action": "inject"}
    assert "requirements_notice" in output["preflight"]
    assert measure_output(output) <= 3000
    assert source == before
    full = context_output(source)
    assert full["preflight"] == before["preflight"]
    assert full["constraints"] == before["constraints"]


@pytest.mark.parametrize(
    "difference",
    [
        {"version": 4},
        {"statement": "Only delete records after explicit authorization."},
        {"intervention": {"action": "inject_with_warning", "reason": "conflicting"}},
        {"qualification": "Production migrations require separate approval."},
    ],
)
def test_compact_does_not_hide_different_requirement_revisions_or_qualifications(
    difference: dict,
) -> None:
    rule = {"id": "rule", "version": 3, "statement": "Preserve data."}
    requirement = {**rule, **difference}
    source = {"constraints": [rule], "preflight": {"requirements": [requirement]}}

    output = context_output(source, mode="compact", limit=3000)

    assert output["preflight"]["requirements"] == [requirement]
    assert "requirements_notice" not in output["preflight"]


def test_compact_warning_keeps_full_caution_evidence_and_arbitrary_metadata() -> None:
    warning = {
        "type": "historical_failure",
        "message": "Rollback lost access",
        "event": {
            "id": "failure-event",
            "project_id": "project",
            "title": "Rollback lost access",
            "event_type": "failure",
            "content": "Do not restore the old schema before preserving the new data.",
            "occurred_at": "2026-10-29T00:00:00Z",
            "created_at": "2026-10-29T00:01:00Z",
            "idempotency_key": "repeated-storage-key" * 100,
            "source_ref": "evidence://run/123",
            "metadata": {"exception": "Only validated backups may be restored."},
            "links": [{"target_id": "data-rule", "relation": "supports"}],
        },
        "evidence": [{"source_ref": "evidence://run/123"}],
    }
    source = {"preflight": {"decision": "warn", "warnings": [warning]}}
    before = deepcopy(source)

    output = context_output(source, mode="compact", limit=1500)

    compact = output["preflight"]["warnings"][0]
    assert compact["type"] == warning["type"]
    assert compact["message"] == warning["message"]
    assert compact["evidence"] == warning["evidence"]
    assert compact["event"] == {
        key: value
        for key, value in warning["event"].items()
        if key not in {"created_at", "idempotency_key", "title", "event_type"}
    }
    assert source == before
    assert measure_output(output) <= 1500


@pytest.mark.parametrize("location", ["unique_requirement", "warning_content", "warning_metadata"])
def test_compact_still_fails_when_unique_preflight_cautions_cannot_fit(location: str) -> None:
    text = "Never delete customer data without explicit authorization. " * 200
    preflight = {
        "decision": "warn",
        "requirements": [],
        "warnings": [],
    }
    if location == "unique_requirement":
        preflight["requirements"] = [{"id": "only-preflight", "statement": text}]
    elif location == "warning_content":
        preflight["warnings"] = [{"message": "Caution", "event": {"content": text}}]
    else:
        preflight["warnings"] = [{"message": "Caution", "event": {"metadata": {"rule": text}}}]

    output = context_output({"preflight": preflight}, mode="compact", limit=2000)

    assert output["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    assert measure_output(output) <= 2000
