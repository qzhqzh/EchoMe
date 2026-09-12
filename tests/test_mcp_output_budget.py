"""Account for the actual MCP text projection, including older Hub responses."""

import json

import pytest

from echome_mcp.context_output import serialize_context


@pytest.mark.parametrize("limit", [256, 1600, 6000])
def test_old_hub_and_cache_metadata_cannot_silently_exceed_budget(limit):
    result = serialize_context(
        {
            "memories": [{"content": "中文上下文" * 4000}],
            "runtime": {"fallback": "last_known_good", "degraded": True},
            "degradation_error": {"message": "timeout " * 1000},
        },
        compact=True,
        limit=limit,
    )
    payload = json.loads(result)
    assert payload["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    assert payload["output_usage"]["tokens_upper_bound"] == len(result.encode()) <= limit


def test_full_output_retains_existing_fields_and_measures_one_copy():
    result = serialize_context(
        {"memories": [], "retrieval_trace": {"detail": "retained"}}, compact=False, limit=256
    )
    payload = json.loads(result)
    assert payload["retrieval_trace"]["detail"] == "retained"
    assert payload["output_usage"]["limit"] is None
    assert payload["output_usage"]["tokens_upper_bound"] == len(result.encode())


def test_invalid_budget_does_not_recurse():
    with pytest.raises(ValueError, match="at least 256"):
        serialize_context({}, compact=True, limit=1)
