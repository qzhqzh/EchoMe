"""Compare shadow gates on synthetic cases; never load conversations or Hub credentials."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from echome.core.gate_safety import contains_sensitive_input  # noqa: E402
from echome.core.memory_gate import (  # noqa: E402
    GateRequest,
    GateSettings,
    build_systemone_payload,
    decide,
    parse_systemone_answer,
)


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; sample count accompanies this statistic."""
    if not values:
        return None
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count failures separately, and retain dangerous-error denominators."""
    valid = [row for row in rows if row.get("action") is not None]
    raw = [row for row in rows if row.get("model_action") is not None]
    needs_read = [row for row in rows if "retrieve" in row["expected_actions"]]
    no_write = [
        row for row in rows if row["phase"] == "write" and "propose" not in row["expected_actions"]
    ]
    model_rows = [row for row in rows if row.get("provider") in {"kev", "laya"}]
    return {
        "total": len(rows),
        "decisions": len(valid),
        "correct": sum(row["action"] in row["expected_actions"] for row in valid),
        "accuracy": round(
            sum(row["action"] in row["expected_actions"] for row in valid) / len(rows), 4
        )
        if rows
        else None,
        "raw_model_decisions": len(raw),
        "raw_model_correct": sum(row["model_action"] in row["expected_actions"] for row in raw),
        "model_invocations": len(model_rows),
        "rule_decisions": sum(row.get("provider") == "rules" for row in rows),
        "degraded": sum(bool(row.get("degraded")) for row in rows),
        "low_probability": sum(row.get("reason_code") == "low_probability" for row in rows),
        "errors": dict(
            Counter(
                row.get("error") or row["reason_code"]
                for row in rows
                if row.get("error")
                or (row.get("degraded") and row.get("reason_code") != "low_probability")
            )
        ),
        "read_false_skip": sum(row.get("action") == "skip" for row in needs_read),
        "read_required": len(needs_read),
        "write_false_propose": sum(row.get("action") == "propose" for row in no_write),
        "write_should_not_propose": len(no_write),
        "latency_p50_ms": percentile([row["latency_ms"] for row in rows], 0.5),
        "latency_p95_ms": percentile([row["latency_ms"] for row in rows], 0.95),
        "model_latency_p95_ms": percentile([row["latency_ms"] for row in model_rows], 0.95),
        "confusion": dict(
            Counter(
                f"{'|'.join(row['expected_actions'])}->{row.get('action') or 'error'}"
                for row in rows
            )
        ),
    }


async def probe_model(
    request: GateRequest, settings: GateSettings, reverse_options: bool
) -> dict[str, Any]:
    """Evaluation only: measure raw choices without gate rules or probability cutoff."""
    if contains_sensitive_input(request.text) or contains_sensitive_input(
        request.project_hint or ""
    ):
        raise ValueError("Sensitive synthetic cases must only exercise the gate")
    payload = build_systemone_payload(request, settings)
    if reverse_options:
        criteria = payload["questions"]["action"]["criteria"]
        payload["questions"]["action"]["criteria"] = dict(reversed(list(criteria.items())))
    base = settings.base_url or ""
    endpoint = base + ("/systemone" if base.endswith("/v1") else "/v1/systemone")
    started = time.perf_counter()
    result: dict[str, Any] = {
        "provider": settings.provider,
        "model": payload["model"],
        "action": None,
        "model_action": None,
        "model_probability": None,
        "degraded": False,
        "prompt_sha256": hashlib.sha256(
            json.dumps(payload, ensure_ascii=False).encode()
        ).hexdigest(),
    }
    try:
        async with (
            asyncio.timeout(settings.timeout_seconds),
            httpx.AsyncClient(
                timeout=settings.timeout_seconds, follow_redirects=False, trust_env=False
            ) as client,
        ):
            response = await client.post(
                endpoint, json=payload, headers={"Authorization": f"Bearer {settings.api_key}"}
            )
        response.raise_for_status()
        if len(response.content) > 65536:
            raise ValueError("Response too large")
        action, probability = parse_systemone_answer(response.json(), request.phase)
        result.update(action=action, model_action=action, model_probability=probability)
    except httpx.HTTPStatusError as exc:
        result["error"] = f"http_{exc.response.status_code}"
    except (TimeoutError, httpx.TimeoutException):
        result["error"] = "timeout"
    except httpx.HTTPError:
        result["error"] = "transport"
    except (ValueError, TypeError, OverflowError):
        result["error"] = "invalid_response"
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    raw = args.cases.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("synthetic") is not True:
        raise ValueError("This runner accepts synthetic fixtures only")
    cases = [
        case for case in dataset["cases"] if args.split == "all" or case["split"] == args.split
    ]
    if args.limit:
        cases = cases[: args.limit]
    settings = []
    for provider in args.provider:
        settings.append(
            GateSettings.model_validate(
                {
                    "provider": provider,
                    "base_url": getattr(args, f"{provider}_url", None),
                    "api_key": os.environ.get(getattr(args, f"{provider}_key_env", ""), ""),
                    "timeout_seconds": args.timeout,
                    "threshold": args.threshold,
                }
            )
        )
    rows = []
    # Sequential and interleaved: neither service permits concurrent inference.
    for case in cases:
        fields = {key: case[key] for key in GateRequest.model_fields if key in case}
        request = GateRequest.model_validate(fields)
        for config in settings:
            for mode in ("gate", "model") if args.mode == "both" else (args.mode,):
                if mode == "model" and (config.provider == "rules" or case["cohort"] != "semantic"):
                    continue
                if mode == "gate":
                    decision = (await decide(request, config)).model_dump(mode="json")
                else:
                    decision = await probe_model(request, config, args.reverse_options)
                rows.append(
                    {
                        "id": case["id"],
                        "phase": case["phase"],
                        "split": case["split"],
                        "cohort": case["cohort"],
                        "category": case["category"],
                        "expected_actions": case["expected_actions"],
                        "configured_provider": config.provider,
                        "mode": mode,
                        **decision,
                    }
                )
        print(f"Completed {case['id']}", file=sys.stderr, flush=True)
    summaries = {}
    for config in settings:
        for mode in ("gate", "model"):
            selected = [
                row
                for row in rows
                if row["configured_provider"] == config.provider and row["mode"] == mode
            ]
            if selected:
                summaries[f"{config.provider}/{mode}"] = {
                    "all": summarize(selected),
                    "read": summarize([row for row in selected if row["phase"] == "read"]),
                    "write": summarize([row for row in selected if row["phase"] == "write"]),
                    "holdout": summarize([row for row in selected if row["split"] == "holdout"]),
                }
    return {
        "schema_version": "echome.memory-gate-eval.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "case_set_sha256": hashlib.sha256(raw).hexdigest(),
        "threshold": args.threshold,
        "timeout_seconds": args.timeout,
        "reverse_options": args.reverse_options,
        "summaries": summaries,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", action="append", choices=["rules", "kev", "laya"])
    parser.add_argument(
        "--cases", type=Path, default=ROOT / "tests/fixtures/memory_gate_cases.json"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["gate", "model", "both"], default="both")
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reverse-options", action="store_true")
    for provider, port in (("kev", 18641), ("laya", 18642)):
        parser.add_argument(f"--{provider}-url", default=f"http://127.0.0.1:{port}")
        parser.add_argument(
            f"--{provider}-key-env", default=f"ECHOME_GATE_{provider.upper()}_API_KEY"
        )
    args = parser.parse_args()
    args.provider = args.provider or ["rules"]
    try:
        result = asyncio.run(evaluate(args))
    except (ValueError, OSError):
        parser.exit(2, "Invalid synthetic fixture, gate settings, or local file access\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["summaries"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
