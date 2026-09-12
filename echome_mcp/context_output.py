"""Account for the actual context copy sent to MCP clients, including fallback."""

import json
from typing import Any


def serialize_context(context: dict[str, Any], *, compact: bool, limit: int) -> str:
    if compact and limit < 256:
        raise ValueError("max_output_tokens must be at least 256")
    # Use the same conservative, model-independent counter as the Hub. The
    # client may consume text, structuredContent, or both: this counts ONE copy.
    context["output_usage"] = {
        "tokens_upper_bound": 0,
        "counter": "utf8_bytes_upper_bound",
        "representation": "single_compact_json",
        "limit": limit if compact else None,
    }
    while True:
        encoded = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        size = len(encoded.encode("utf-8"))
        if context["output_usage"]["tokens_upper_bound"] == size:
            break
        context["output_usage"]["tokens_upper_bound"] = size
    if compact and size > limit:
        # This also catches older Hubs that ignore output_mode and cache
        # degradation metadata added after the original response was measured.
        return serialize_context(
            {
                "schema_version": "echome.error.v1",
                "error": {
                    "code": "OUTPUT_BUDGET_TOO_SMALL",
                    "retryable": False,
                    "minimum_tokens": size,
                },
            },
            compact=True,
            limit=limit,
        )
    return encoded
