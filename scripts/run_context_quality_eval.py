"""Run the fixed context quality cases against a live EchoMe Hub."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import yaml

HUB_DIR = Path(__file__).resolve().parents[1] / "hub"
sys.path.insert(0, str(HUB_DIR))

from app.services.context_quality_eval import (  # noqa: E402
    evaluate_context_quality,
    load_context_quality_cases,
)

CONFIG_FILE = Path.home() / ".echome" / "config.yaml"


def _config() -> dict[str, str]:
    payload = (
        yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        if CONFIG_FILE.exists()
        else {}
    )
    return {
        "hub_url": str(payload.get("hub_url", "http://127.0.0.1:20000")).rstrip("/"),
        "token": str(payload.get("token", "")),
    }


async def _post(
    client: httpx.AsyncClient,
    path: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(path, json=body)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected object from {path}")
    return payload


async def run_eval(
    base_url: str,
    project_id: str,
    *,
    k: int = 10,
    case_ids: set[str] | None = None,
    include_results: bool = False,
    snapshot_key: str | None = None,
    snapshot_trigger: str = "manual",
) -> dict[str, Any]:
    config = _config()
    cases_payload = load_context_quality_cases()
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
    }
    results = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), headers=headers, timeout=90
    ) as client:
        for case in cases_payload["cases"]:
            if case_ids and case["id"] not in case_ids:
                continue
            started = perf_counter()
            context = await _post(
                client,
                "/api/v1/project-knowledge/context",
                {
                    "project_id": project_id,
                    "task": case["query"],
                    "changed_paths": case.get("changed_paths", []),
                    "mode": "impact"
                    if case.get("mode") == "preflight"
                    else case.get("mode", "local"),
                    "limit": k,
                    "token_budget": 6000,
                    "as_of": case.get("as_of"),
                    "record_run": False,
                },
            )
            preflight = None
            if case.get("mode") == "preflight":
                preflight = await _post(
                    client,
                    "/api/v1/project-knowledge/preflight",
                    {
                        "project_id": project_id,
                        "task": case["query"],
                        "changed_paths": case.get("changed_paths", []),
                        "planned_actions": case.get("planned_actions", []),
                        "limit": k,
                    },
                )
            results.append(
                {
                    "case_id": case["id"],
                    "context": context,
                    "preflight": preflight,
                    "latency_ms": (perf_counter() - started) * 1000,
                    "token_used": context.get("token_used"),
                }
            )
    report = evaluate_context_quality(cases_payload, results, k=k)
    report["base_url"] = base_url.rstrip("/")
    if snapshot_key:
        if case_ids:
            raise ValueError("A quality snapshot must include the complete fixed dataset")
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=90
        ) as client:
            report["snapshot"] = await _post(
                client,
                "/api/v1/project-knowledge/eval/snapshots",
                {
                    "project_id": project_id,
                    "results": results,
                    "k": k,
                    "trigger": snapshot_trigger,
                    "dry_run": True,
                    "idempotency_key": snapshot_key,
                },
            )
    if include_results:
        report["raw_results"] = results
    return report


def main() -> None:
    config = _config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=config["hub_url"])
    parser.add_argument("--project-id", default="qzhqzh/EchoMe")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--allow-fail", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--include-results", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--snapshot-key")
    parser.add_argument(
        "--snapshot-trigger", choices=("manual", "background", "ci"), default="manual"
    )
    args = parser.parse_args()
    report = asyncio.run(
        run_eval(
            args.base_url,
            args.project_id,
            k=args.k,
            case_ids=set(args.case_id) or None,
            include_results=args.include_results,
            snapshot_key=args.snapshot_key,
            snapshot_trigger=args.snapshot_trigger,
        )
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    if not report["passed"] and not args.allow_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
