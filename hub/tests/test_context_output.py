"""Complete-output budgets must retain rules or return an explicit failure."""

import json

import pytest

from app.services.context_completion import completion_contract
from app.services.context_output import context_output, measure_output


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
