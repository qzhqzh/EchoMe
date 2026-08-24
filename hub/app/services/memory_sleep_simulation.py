"""Deterministic before/after simulation for Memory Sleep v2 plans."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.models.memory import Memory
from app.services.memory_retrieval import lexical_memory_similarity, memory_query_tokens
from app.services.token_counter import count_tokens

RETRIEVABLE_STATUSES = {"active", "ai_review"}


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _plan_fingerprint(plan: dict[str, Any], memories: list[Memory]) -> str:
    clean_plan = {key: value for key, value in plan.items() if key != "server_simulation"}
    payload = {
        "plan": clean_plan,
        "sources": [
            {
                "id": str(memory.id),
                "status": memory.status,
                "sleep_state": memory.sleep_state,
                "updated_at": _iso(memory.updated_at),
            }
            for memory in sorted(memories, key=lambda item: str(item.id))
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _rank(
    query: str,
    memories: list[dict[str, Any]],
    expected_ids: set[str],
    top_k: int,
) -> tuple[int | None, list[str]]:
    tokens = set(memory_query_tokens(query))
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for memory in memories:
        score = lexical_memory_similarity(
            tokens,
            title=memory["title"],
            tags=memory["tags"],
            content=memory["content"],
        )
        if score >= 0.3:
            ranked.append((score, int(memory["priority"]), memory))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
    selected = [item[2] for item in ranked[:top_k]]
    rank = next(
        (
            index
            for index, item in enumerate(selected, 1)
            if expected_ids & set(item["equivalent_source_ids"])
        ),
        None,
    )
    return rank, [item["id"] for item in selected]


def simulate_sleep_plan_v2(
    candidate_memories: list[Memory],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Project candidate-local lexical retrieval and source footprint after a v2 plan."""
    by_id = {str(memory.id): memory for memory in candidate_memories}
    input_ids = {str(item) for item in plan["input_memory_ids"]}
    inputs = [by_id[memory_id] for memory_id in sorted(input_ids) if memory_id in by_id]
    failures: list[str] = []
    warnings: list[str] = []

    if len(inputs) != len(input_ids):
        failures.append("input_memory_missing")

    preconditions = {str(item["memory_id"]): item for item in plan.get("preconditions", [])}
    for memory in inputs:
        expected = preconditions.get(str(memory.id))
        if expected is None:
            failures.append(f"precondition_missing:{memory.id}")
            continue
        if expected.get("status") != memory.status:
            failures.append(f"precondition_status_changed:{memory.id}")
        if expected.get("sleep_state") != memory.sleep_state:
            failures.append(f"precondition_sleep_state_changed:{memory.id}")
        try:
            expected_updated = datetime.fromisoformat(
                str(expected.get("updated_at", "")).replace("Z", "+00:00")
            )
        except ValueError:
            failures.append(f"precondition_updated_at_invalid:{memory.id}")
        else:
            if _iso(expected_updated) != _iso(memory.updated_at):
                failures.append(f"precondition_updated_at_changed:{memory.id}")

    status_actions: dict[str, dict[str, Any]] = {}
    terminal_ids: set[str] = set()
    created: list[dict[str, Any]] = []
    for action in plan["actions"]:
        op = action["op"]
        if op == "create_memory":
            payload = action["memory"]
            created.append(
                {
                    "id": f"client_ref:{action['client_ref']}",
                    "title": payload["title"],
                    "content": payload["content"],
                    "tags": list(payload.get("tags", [])),
                    "priority": int(payload.get("priority", 5)),
                    "token_count": count_tokens(payload["content"]),
                    "equivalent_source_ids": [str(item) for item in action["derived_from"]],
                }
            )
        elif op in {"keep_memory", "update_memory_status"}:
            memory_id = str(action["memory_id"])
            terminal_ids.add(memory_id)
            if op == "update_memory_status":
                status_actions[memory_id] = action
        elif op == "needs_human":
            memory_ids = action.get("memory_ids") or [action.get("memory_id")]
            terminal_ids.update(str(item) for item in memory_ids if item)
            failures.append("needs_human_unresolved")

    coverage = len(terminal_ids & input_ids) / len(input_ids) if input_ids else 0.0
    if coverage < 1:
        failures.append("source_coverage_below_gate")

    before = [
        {
            "id": str(memory.id),
            "title": memory.title,
            "content": memory.content,
            "tags": list(memory.tags or []),
            "priority": memory.priority,
            "token_count": memory.token_count,
            "equivalent_source_ids": [str(memory.id)],
        }
        for memory in candidate_memories
        if memory.status in RETRIEVABLE_STATUSES
    ]
    after: list[dict[str, Any]] = []
    for item in before:
        action = status_actions.get(str(item["id"]))
        if action and action["to_status"] not in RETRIEVABLE_STATUSES:
            continue
        after.append(item)
    after.extend(created)

    replay_results: list[dict[str, Any]] = []
    regressions = 0
    scored_cases = 0
    for case in plan["replay_cases"]:
        expected_ids = {str(item) for item in case["expected_memory_ids"]}
        before_rank, before_ids = _rank(case["query"], before, expected_ids, case["top_k"])
        after_rank, after_ids = _rank(case["query"], after, expected_ids, case["top_k"])
        if before_rank is not None:
            scored_cases += 1
        regressed = before_rank is not None and (after_rank is None or after_rank > before_rank)
        regressions += regressed
        replay_results.append(
            {
                "case_id": case["case_id"],
                "before_rank": before_rank,
                "after_rank": after_rank,
                "regressed": regressed,
                "before_result_ids": before_ids,
                "after_result_ids": after_ids,
            }
        )

    gates = {
        "min_source_coverage": 1.0,
        "max_replay_regressions": 0,
        "max_token_growth_ratio": 0.1,
        "min_scored_replay_cases": 1,
        **plan.get("quality_gates", {}),
    }
    before_tokens = sum(max(0, int(memory.token_count or 0)) for memory in inputs)
    retained_input_tokens = sum(
        max(0, int(memory.token_count or 0))
        for memory in inputs
        if not (
            (action := status_actions.get(str(memory.id)))
            and action["to_status"] not in RETRIEVABLE_STATUSES
        )
    )
    after_tokens = retained_input_tokens + sum(item["token_count"] for item in created)
    raw_token_growth_ratio = (
        (after_tokens - before_tokens) / before_tokens
        if before_tokens
        else (0.0 if after_tokens == 0 else 1.0)
    )
    if coverage < float(gates["min_source_coverage"]):
        failures.append("source_coverage_gate_failed")
    if regressions > int(gates["max_replay_regressions"]):
        failures.append("replay_regression_gate_failed")
    if raw_token_growth_ratio > float(gates["max_token_growth_ratio"]):
        failures.append("token_growth_gate_failed")
    if scored_cases < int(gates["min_scored_replay_cases"]):
        failures.append("insufficient_scored_replay_cases")
    if scored_cases < len(plan["replay_cases"]):
        warnings.append("some_replay_cases_lacked_a_lexical_baseline_hit")

    return {
        "schema_version": "memory_sleep_simulation.v1",
        "simulator": "candidate_local_lexical",
        "read_only": True,
        "source_mutation": "none",
        "plan_fingerprint": _plan_fingerprint(plan, inputs),
        "source_coverage": round(coverage, 4),
        "input_memory_count": len(input_ids),
        "created_memory_count": len(created),
        "before_token_footprint": before_tokens,
        "after_token_footprint": after_tokens,
        "token_growth_ratio": round(raw_token_growth_ratio, 4),
        "scored_replay_cases": scored_cases,
        "replay_regressions": regressions,
        "quality_gates": gates,
        "replay_cases": replay_results,
        "warnings": sorted(set(warnings)),
        "failures": sorted(set(failures)),
        "passed": not failures,
        "simulated_at": datetime.now(timezone.utc).isoformat(),
    }
