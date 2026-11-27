"""Replay explicitly selected, local user messages against read-only discovery.

The manifest contains source locations and hashes, not complete transcripts. Results
retain reference metadata only. Recall checks cover known-useful references; they
do not mistake a smaller result set or task completion for measured user benefit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from echome.core.config import Config  # noqa: E402
from echome.core.gate_safety import contains_sensitive_input, validate_provider_url  # noqa: E402


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def source_prompt(case: dict[str, Any]) -> str:
    """Only read the selected native user message, never model reasoning."""
    if case.get("kind") == "synthetic":
        text = str(case["synthetic_text"])
        if not text.strip() or len(text.encode()) > 65536 or contains_sensitive_input(text):
            raise ValueError("Synthetic query is empty, oversized or sensitive")
        return text
    source = case["source"]
    path = Path(source["path"])
    if not path.exists():
        # Archiving can move the rollout during a long evaluation. Resolve the
        # same native thread, then still require the exact reviewed line hash.
        match = re.search(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", path.name)
        thread_id = source.get("thread_id") or (match.group() if match else None)
        if not thread_id:
            raise ValueError("Missing source and no stable thread identity")
        database = Path.home() / ".codex" / "state_5.sqlite"
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT rollout_path FROM threads WHERE id = ?", (thread_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Native thread cannot be resolved")
        path = Path(row[0])
        source["resolved_path"] = str(path)
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            if number != source["line"]:
                continue
            event = json.loads(line)
            item = event.get("payload", {})
            if (
                event.get("type") != "response_item"
                or item.get("type") != "message"
                or item.get("role") != "user"
            ):
                raise ValueError("Selected source is not a native user message")
            text = "\n".join(block.get("text", "") for block in item.get("content", []))
            if digest(text) != source["sha256"]:
                raise ValueError("Selected source no longer matches its reviewed hash")
            if len(text.encode()) > 65536 or contains_sensitive_input(text):
                raise ValueError("Selected source is oversized or sensitive; excluded from replay")
            return text
    raise ValueError("Selected source line is absent")


def references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Do not persist source bodies, tasks, account data, or response headers."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind in ("memories", "memory_index", "knowledge_refs", "constraints"):
        for item in payload.get(kind, []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            identifier = str(item["id"])
            if identifier in seen:
                continue
            seen.add(identifier)
            entry = {
                key: item[key]
                for key in ("id", "title", "kind", "source", "revision", "read", "warning")
                if key in item
            }
            entry["collection"] = kind
            result.append(entry)
    return result


def reference_contract(projection: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that envelope cleanup preserves citations, cautions and read recipes."""
    return [
        {
            key: item[key]
            for key in (
                "id",
                "warning",
                "revision",
                "review_state",
                "read",
                "read_tool",
                "read_args",
                "needs_expansion",
            )
            if key in item and item[key] is not None
        }
        for kind in ("memory_index", "knowledge_refs")
        for item in projection.get(kind, [])
    ]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2)


async def expand_reference(client: httpx.AsyncClient, ref: dict[str, Any]) -> dict[str, Any]:
    """Verify a selected read recipe without storing its body or executing it."""
    identifier = str(UUID(str(ref["id"])))
    params: dict[str, Any] = {}
    read = ref.get("read", {})
    arguments = read.get("arguments", {})
    if read.get("tool") == "echome_knowledge_read":
        path = "/api/v1/knowledge/records/" + identifier
        revision = arguments.get("data", {}).get("revision") or ref.get("revision")
        if revision is not None:
            params["revision"] = revision
    elif read.get("tool") == "echome_scene_read":
        selector = str(arguments.get("selector", ""))
        if not selector or "/" in selector or ".." in selector:
            raise ValueError("Invalid scene read recipe")
        path = "/api/v1/scenarios/knowledge/" + quote(selector, safe="")
    else:
        path = "/api/v1/memories/" + identifier
    response = await client.get(path, params=params)
    response.raise_for_status()
    payload = response.json()
    if read.get("tool") == "echome_scene_read":
        payload = next((e for e in payload.get("entries", []) if e.get("id") == identifier), {})
    complete = bool(payload) and not payload.get("error")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": identifier,
        "ok": complete,
        "status": response.status_code,
        "expanded_chars": len(serialized),
        "content_sha256": digest(serialized),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [check for row in rows for check in row.get("known_useful_checks", [])]
    return {
        "cases": len(rows),
        "errors": sum(bool(row.get("error")) for row in rows),
        "candidate_references": sum(len(row.get("references", [])) for row in rows),
        "empty_cases": sum(not row.get("references") and not row.get("error") for row in rows),
        "known_useful_groups": len(checks),
        "known_useful_groups_found": sum(check["found"] for check in checks),
        "latency_p50_ms": percentile([row["latency_ms"] for row in rows], 0.5),
        "latency_p95_ms": percentile([row["latency_ms"] for row in rows], 0.95),
        "output_bytes": sum(row.get("response_bytes", 0) for row in rows),
        "discovery_injection_chars": sum(row.get("discovery_injection_chars", 0) for row in rows),
    }


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    manifest = json.loads(args.manifest.read_text())
    config = Config.load()
    base_url = validate_provider_url(args.base_url or config.hub_url)
    expansion_url = validate_provider_url(args.expansion_base_url or base_url)
    old_projection = None
    if args.compare_projection_snapshot:
        spec = importlib.util.spec_from_file_location(
            "echome_projection_evaluation_snapshot", args.compare_projection_snapshot
        )
        if spec is None or spec.loader is None:
            raise ValueError("Cannot load reviewed projection snapshot")
        old_projection = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old_projection)
    rows: list[dict[str, Any]] = []
    async with (
        httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": "Bearer " + config.token},
            timeout=15,
            trust_env=False,
            follow_redirects=False,
        ) as client,
        httpx.AsyncClient(
            base_url=expansion_url,
            headers={"Authorization": "Bearer " + config.token},
            timeout=15,
            trust_env=False,
            follow_redirects=False,
        ) as expansion_client,
    ):
        for case in manifest["cases"]:
            if args.case and case["id"] not in args.case:
                continue
            prompt = source_prompt(case)
            if args.mode == "candidate":
                from echome.core.hook_prompt import normalize_hook_prompt

                prompt = normalize_hook_prompt(prompt)
            body: dict[str, Any] = {
                "task": prompt,
                "mode": "personal",
                "record_run": False,
                "output_mode": "compact",
                "max_output_tokens": 10000,
                "token_budget": 3000,
                "limit": 3,
            }
            if args.mode == "candidate":
                from echome.core.hook_project import local_project_hints

                body = {
                    "task": prompt,
                    "project_hint": case["cwd"],
                    "limit": 3,
                    "max_output_tokens": 10000,
                    "project_hints": local_project_hints(case["cwd"]),
                }
            row: dict[str, Any] = {
                "id": case["id"],
                "kind": case.get("kind", "real"),
                "summary": case["summary"],
                "source": case.get("source"),
                "query_sha256": digest(prompt),
                "query_chars": len(prompt),
                "known_useful_checks": [],
            }
            started = time.monotonic()
            try:
                response = await client.post(args.endpoint, json=body)
                row["http_status"] = response.status_code
                row["response_bytes"] = len(response.content)
                response.raise_for_status()
                payload = response.json()
                if payload.get("error"):
                    row["error"] = payload["error"].get("code", "hub_error")
                row["references"] = references(payload)
                from echome.core.task_hook import _context_index, _hook_output

                discovery = _context_index(payload) if not payload.get("error") else {}
                projected = _hook_output({"discovery": discovery}) if discovery else {}
                injected = projected.get("hookSpecificOutput", {}).get("additionalContext", "")
                row["discovery_injection_chars"] = len(injected)
                row["projection_includes_habits"] = False
                if old_projection is not None:
                    old_discovery = old_projection._context_index(payload)
                    old_output = (
                        old_projection._hook_output({"discovery": old_discovery})
                        if old_discovery
                        else {}
                    )
                    old_text = old_output.get("hookSpecificOutput", {}).get("additionalContext", "")
                    row["projection_before_chars"] = len(old_text)
                    row["projection_contract_preserved"] = reference_contract(
                        old_discovery
                    ) == reference_contract(discovery)
                row["scope"] = payload.get("scope")
                row["project_resolution"] = payload.get("project_resolution")
                identifiers = {item["id"] for item in row["references"]}
                for group in case.get("known_useful_groups", []):
                    row["known_useful_checks"].append(
                        {
                            "label": group["label"],
                            "found": bool(identifiers.intersection(group["any_ids"])),
                            "expected_ids": group["any_ids"],
                        }
                    )
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                row["error"] = type(exc).__name__
            row["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
            if args.expand_known and not row.get("error"):
                expected = {
                    identifier
                    for group in case.get("known_useful_groups", [])
                    for identifier in group["any_ids"]
                }
                row["expansions"] = []
                for ref in row.get("references", []):
                    if ref["id"] not in expected:
                        continue
                    try:
                        row["expansions"].append(await expand_reference(expansion_client, ref))
                    except (httpx.HTTPError, ValueError, TypeError) as exc:
                        row["expansions"].append(
                            {
                                "id": ref["id"],
                                "ok": False,
                                "error": type(exc).__name__,
                                "status": exc.response.status_code
                                if isinstance(exc, httpx.HTTPStatusError)
                                else None,
                            }
                        )
            rows.append(row)
            # A single request in flight; no model calls or retries.
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "refs": len(row.get("references", [])),
                        "error": row.get("error"),
                    }
                ),
                flush=True,
            )
            if row.get("http_status") in {401, 403, 404}:
                # Wrong endpoint/auth is shared across the batch. Stop rather
                # than emit repeated failures or count the rest as empty hits.
                break
    return {
        "schema": "echome.discovery-evaluation.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "planned_cases": sum(
            not args.case or case["id"] in args.case for case in manifest["cases"]
        ),
        "manifest_sha256": digest(args.manifest.read_text()),
        "endpoint": args.endpoint,
        "summary": summarize(rows),
        "cases": rows,
        "limits": [
            "Selected real-message replay, not a random sample or a new live outcome.",
            "Known useful references are recall checks, not exhaustive relevance labels.",
            "Unclassified references require human semantic review; empty is not automatically good.",
            "No transcript or source body is copied; source locations and reviewed hashes are retained.",
            "No memory, feedback, context outcome, or recorded context run is written.",
            "Discovery injection character counts use the same Hook projection; habit cards are excluded.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--endpoint", default="/api/v1/context")
    parser.add_argument("--case", action="append")
    parser.add_argument("--expand-known", action="store_true")
    parser.add_argument("--expansion-base-url")
    parser.add_argument("--compare-projection-snapshot", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
