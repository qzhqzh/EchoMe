"""Bound the complete context projection, including diagnostics and accounting.

UTF-8 byte length is a conservative token upper bound for byte-based tokenizers.
It is deliberately distinct from the existing content-token estimate and needs
neither an online tokenizer download nor a client-specific model dependency.
"""

import copy
import json
from typing import Any

from app.services.token_counter import count_tokens

MEMORY_INDEX_NOTICE = (
    "Budget limited memory index: references only, not complete memories or rules. "
    "Expand IDs via GET /api/v1/memories/{id} before use."
)
OUTPUT_BUDGET_NOTICE = "Output budget omitted optional records; request full context for details."


def content_tokens(payload: dict[str, Any]) -> int:
    """Estimate delivered source text only, excluding envelopes and references."""
    return sum(
        count_tokens(item[key])
        for kind in ("constraints", "memories", "artifacts", "evidence")
        for item in payload.get(kind, [])
        for key in ("content", "statement", "excerpt")
        if isinstance(item.get(key), str) and item[key]
    )


def memory_reference(item: dict[str, Any]) -> dict[str, Any]:
    """A reference is never a truncated substitute for a memory's instructions."""
    reference = {"id": item["id"], "title": item.get("title", ""), "needs_expansion": True}
    if item.get("intervention"):
        reference["intervention"] = copy.deepcopy(item["intervention"])
    return reference


def _account_delivery(payload: dict[str, Any], limit: int | None) -> dict[str, Any]:
    payload["delivered_content_tokens"] = content_tokens(payload)
    references = payload.get("memory_index", [])
    payload["memory_index_tokens"] = (
        count_tokens(json.dumps(references, ensure_ascii=False, separators=(",", ":")))
        if references
        else 0
    )
    return account_output(payload, limit)


def _budget_error(output: dict[str, Any], limit: int) -> dict[str, Any]:
    return account_output(
        {
            "schema_version": "echome.error.v1",
            "error": {
                "code": "OUTPUT_BUDGET_TOO_SMALL",
                "retryable": False,
                "minimum_tokens": measure_output(output),
            },
        },
        limit,
    )


def measure_output(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def account_output(payload: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    payload["output_usage"] = {
        "tokens_upper_bound": 0,
        "counter": "utf8_bytes_upper_bound",
        "representation": "single_compact_json",
        "limit": limit,
    }
    # The decimal counter contributes to the measured representation too.
    while True:
        size = measure_output(payload)
        if payload["output_usage"]["tokens_upper_bound"] == size:
            return payload
        payload["output_usage"]["tokens_upper_bound"] = size


def context_output(
    context: dict[str, Any],
    *,
    mode: str = "full",
    limit: int = 6000,
) -> dict[str, Any]:
    output = copy.deepcopy(context)
    # token_used retains its existing compiler-budget meaning. These counters
    # use the same estimator on source text before and after output projection.
    output["compiled_content_tokens"] = content_tokens(context)
    if mode == "full":
        return _account_delivery(output, None)
    output["output_mode"] = "compact"
    for key in ("task", "retrieval_trace", "preflight", "resolution"):
        output.pop(key, None)
    preflight = context.get("preflight")
    if isinstance(preflight, dict):
        output["preflight"] = copy.deepcopy(
            {
                key: preflight[key]
                for key in ("decision", "warnings", "requirements", "stale_warnings", "unknowns")
                if key in preflight
            }
        )
    if output.get("project"):
        output["project"].pop("description", None)
    if isinstance(output.get("runtime"), dict):
        output["runtime"].pop("latency_ms", None)
    if not output.get("runtime", {}).get("resolution_required"):
        output.pop("project_resolution", None)
    for kind in ("memories", "constraints"):
        for item in output.get(kind, []):
            item.pop("selection_reasons", None)
            # The intervention and policy mode remain; repeated assessment
            # evidence is available in the recorded run's diagnostics.
            item.pop("reliability", None)
            intervention = item.get("intervention")
            if (
                isinstance(intervention, dict)
                and intervention.get("action") == "inject"
                and intervention.get("reason") == "support_state:current_supported"
            ):
                intervention.pop("reason")
    policy = output.get("context_policy")
    if isinstance(policy, dict):
        # Full diagnostics retain the ID lists and repeated aggregate counts.
        # Keep modes, enforcement, fallback warnings and source-mutation policy.
        for key in (
            "decision_counts",
            "would_exclude",
            "excluded",
            "diagnostic_token_overhead",
            "budget_accounting",
        ):
            policy.pop(key, None)
        if policy.get("requested_mode") == policy.get("effective_mode"):
            policy.pop("requested_mode", None)
    run_id = output.get("context_run_id")
    output["diagnostics"] = {
        "href": f"/api/v1/context/runs/{run_id}" if run_id else None,
        "retry_output_mode": "full",
    }
    output["omitted_counts"] = dict(output.get("omitted_counts", {}))
    if output.get("answerability") == "supported" and not any(
        output.get(key) for key in ("constraints", "memories", "artifacts", "evidence")
    ):
        output["answerability"] = "insufficient_evidence"
    if measure_output(_account_delivery(output, limit)) <= limit:
        return output

    protected_ids = {str(item.get("id")) for item in output.get("must_include", [])}
    originals = {key: output.get(key, []) for key in ("memories", "artifacts", "evidence")}
    retained: dict[str, set[int]] = {}
    for kind, items in originals.items():
        retained[kind] = {
            index
            for index, item in enumerate(items)
            if str(item.get("id")) in protected_ids
            or item.get("type") == "guardrail"
            or item.get("layer") == "L0"
        }
        output[kind] = [item for index, item in enumerate(items) if index in retained[kind]]
        omitted = len(items) - len(output[kind])
        if omitted:
            output["omitted_counts"][kind] = output["omitted_counts"].get(kind, 0) + omitted
    references = output.pop("memory_index", [])
    if OUTPUT_BUDGET_NOTICE not in output.setdefault("unknowns", []):
        output["unknowns"].append(OUTPUT_BUDGET_NOTICE)
    original_answerability = output.get("answerability")

    def fits() -> bool:
        if original_answerability not in {"conflicted", "insufficient_evidence"}:
            output["answerability"] = (
                "partial"
                if any(
                    output.get(key) for key in ("constraints", "memories", "artifacts", "evidence")
                )
                else "insufficient_evidence"
            )
        return measure_output(_account_delivery(output, limit)) <= limit

    # Start with complete mandatory records, never truncated rules. Greedy
    # packing follows compiler relevance order but skips an oversized record.
    if not fits():
        return _budget_error(output, limit)
    for kind, items in originals.items():
        mandatory_indices = retained[kind].copy()
        for index in range(len(items)):
            if index in retained[kind]:
                continue
            retained[kind].add(index)
            output[kind] = [row for i, row in enumerate(items) if i in retained[kind]]
            output["omitted_counts"][kind] -= 1
            if not output["omitted_counts"][kind]:
                output["omitted_counts"].pop(kind)
            if not fits():
                retained[kind].remove(index)
                output[kind] = [row for i, row in enumerate(items) if i in retained[kind]]
                output["omitted_counts"][kind] = output["omitted_counts"].get(kind, 0) + 1
        if kind == "memories" and retained[kind] == mandatory_indices:
            references = [
                memory_reference(item)
                for index, item in enumerate(items) if index not in mandatory_indices
            ] + references
            if references:
                output["memory_index"] = []
                if set(output["omitted_counts"]) <= {"memories"}:
                    output["unknowns"].remove(OUTPUT_BUDGET_NOTICE)
                if MEMORY_INDEX_NOTICE not in output["unknowns"]:
                    output["unknowns"].append(MEMORY_INDEX_NOTICE)
                for reference in references:
                    output["memory_index"].append(reference)
                    if not fits():
                        output["memory_index"].pop()
                if not output["memory_index"]:
                    # Even a reference cannot fit alongside the safety envelope.
                    output["memory_index"] = references[:1]
                    fits()
                    return _budget_error(output, limit)
    output["omitted_counts"] = {
        key: count for key, count in output["omitted_counts"].items() if count
    }
    if not fits():
        return _budget_error(output, limit)
    return output
