"""Bound the complete context projection, including diagnostics and accounting.

UTF-8 byte length is a conservative token upper bound for byte-based tokenizers.
It is deliberately distinct from the existing content-token estimate and needs
neither an online tokenizer download nor a client-specific model dependency.
"""

import copy
import json
from typing import Any


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
    if mode == "full":
        return account_output(output)
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
    if not output.get("runtime", {}).get("resolution_required"):
        output.pop("project_resolution", None)
    for kind in ("memories", "constraints"):
        for item in output.get(kind, []):
            item.pop("selection_reasons", None)
            # The intervention and policy mode remain; repeated assessment
            # evidence is available in the recorded run's diagnostics.
            item.pop("reliability", None)
    run_id = output.get("context_run_id")
    output["diagnostics"] = {
        "href": f"/api/v1/context/runs/{run_id}" if run_id else None,
        "retry_output_mode": "full",
    }
    output["omitted_counts"] = {}
    protected_ids = {str(item.get("id")) for item in output.get("must_include", [])}
    # Preserve constraints, guardrails, conflicts, unknowns, provenance IDs and
    # completion. Remove optional items as whole records, never partial rules.
    for kind in ("evidence", "artifacts", "memories"):
        items = output.get(kind, [])
        for index in range(len(items) - 1, -1, -1):
            if measure_output(account_output(output, limit)) <= limit:
                return output
            item = items[index]
            if (
                str(item.get("id")) in protected_ids
                or item.get("type") == "guardrail"
                or item.get("layer") == "L0"
            ):
                continue
            items.pop(index)
            output["omitted_counts"][kind] = output["omitted_counts"].get(kind, 0) + 1
            warning = "Output budget omitted optional records; request full context for details."
            if warning not in output.setdefault("unknowns", []):
                output["unknowns"].append(warning)
            if output.get("answerability") == "supported":
                output["answerability"] = "partial"
            if output.get("answerability") != "conflicted" and not any(
                output.get(key) for key in ("constraints", "memories", "artifacts", "evidence")
            ):
                output["answerability"] = "insufficient_evidence"
    if measure_output(account_output(output, limit)) <= limit:
        return output
    # No usable context was delivered. Do not claim success or silently remove
    # safety-relevant records just to fit the envelope.
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
