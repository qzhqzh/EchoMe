"""Budgeted delivery preserves complete source text and distinguishes references."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.api.context_runtime import get_unified_context
from app.models.project_knowledge import ContextRun
from app.schemas.context_runtime import UnifiedContextRequest
from app.services.context_completion import completion_contract
from app.services.context_output import (
    MEMORY_INDEX_NOTICE,
    content_tokens,
    context_output,
    measure_output,
)

RUN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LONG_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SHORT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def memory(memory_id: str, title: str, content: str) -> dict:
    return {
        "id": memory_id,
        "title": title,
        "content": content,
        "type": "method",
        "layer": "L1",
        "status": "active",
        "tags": [],
        "updated_at": "2026-09-22T12:34:56.123456+00:00",
        "intervention": {
            "action": "inject",
            "include": True,
            "reason": "support_state:current_supported",
        },
        "reliability": {"reason_codes": ["diagnostic" * 1000]},
    }


def personal_context() -> dict:
    return {
        "schema_version": "echome.context.v1",
        "scope": "personal",
        "project": None,
        "task": "修改代码前确认个人开发约定",
        "mode": "personal",
        "constraints": [],
        "memories": [
            memory(LONG_ID, "完整开发约定", "部署环境与数据不可混淆。" * 500),
            memory(SHORT_ID, "沟通偏好", "中文简洁回复。"),
        ],
        "artifacts": [],
        "evidence": [],
        "conflicts": [],
        "stale_warnings": [],
        "unknowns": [],
        "token_budget": 4500,
        "token_used": 2200,
        "context_policy": {
            "schema_version": 1,
            "requested_mode": "shadow",
            "effective_mode": "shadow",
            "enforced": False,
            "decision_counts": {"inject": 20},
            "would_exclude": {"memories": [LONG_ID] * 20, "constraints": []},
            "excluded": {"memories": [], "constraints": []},
            "source_mutation": "none",
            "budget_accounting": "diagnostics_excluded_from_token_used",
            "diagnostic_token_overhead": 1300,
        },
        "context_run_id": RUN_ID,
        "completion_contract": completion_contract(RUN_ID),
        "preflight": None,
        "answerability": "supported",
        "recommended_actions": [],
        "resolution": None,
        "project_resolution": None,
        "runtime": {
            "request_id": RUN_ID,
            "route": "personal",
            "degraded": False,
            "fallback": None,
            "latency_ms": 230.51,
        },
    }


@pytest.mark.parametrize("limit", [2000, 2200, 3000, 4500])
def test_chinese_short_memory_survives_long_first_record_and_policy_envelope(limit: int) -> None:
    source = personal_context()
    before = deepcopy(source)

    output = context_output(source, mode="compact", limit=limit)

    assert [item["id"] for item in output["memories"]] == [SHORT_ID]
    assert output["memories"][0]["content"] == source["memories"][1]["content"]
    assert output["memories"][0]["updated_at"] == source["memories"][1]["updated_at"]
    assert output["context_policy"]["effective_mode"] == "shadow"
    assert output["context_policy"]["enforced"] is False
    assert "would_exclude" not in output["context_policy"]
    assert output["completion_contract"] == source["completion_contract"]
    assert output["token_used"] == 2200
    assert output["compiled_content_tokens"] == content_tokens(source)
    assert 0 < output["delivered_content_tokens"] < output["compiled_content_tokens"]
    assert output["memory_index_tokens"] == 0
    assert output["omitted_counts"] == {"memories": 1}
    assert output["answerability"] == "partial"
    assert output["output_usage"]["tokens_upper_bound"] == measure_output(output) <= limit
    assert source == before


def test_relevance_order_is_retained_for_complete_records_that_fit() -> None:
    source = {
        "memories": [
            {"id": "long", "title": "长记录", "content": "过长。" * 3000},
            {"id": "higher", "title": "优先", "content": "甲" * 220},
            {"id": "lower", "title": "次选", "content": "乙" * 220},
        ],
        "answerability": "supported",
    }
    output = context_output(source, mode="compact", limit=1600)

    assert [item["id"] for item in output["memories"]] == ["higher"]
    assert output["memories"][0] == source["memories"][1]
    assert measure_output(output) <= 1600


def test_packing_does_not_upgrade_existing_insufficient_evidence() -> None:
    source = personal_context()
    source["answerability"] = "insufficient_evidence"

    output = context_output(source, mode="compact", limit=2200)

    assert [item["id"] for item in output["memories"]] == [SHORT_ID]
    assert output["answerability"] == "insufficient_evidence"
    assert measure_output(output) <= 2200


@pytest.mark.parametrize("limit", [2000, 3000, 4500])
def test_only_oversized_memories_return_bounded_references_not_partial_rules(limit: int) -> None:
    source = personal_context()
    source["memories"] = source["memories"][:1]
    output = context_output(source, mode="compact", limit=limit)

    assert output["memories"] == []
    assert [(item["id"], item["title"]) for item in output["memory_index"]] == [
        (LONG_ID, source["memories"][0]["title"])
    ]
    assert output["memory_index"][0]["needs_expansion"] is True
    assert "content" not in output["memory_index"][0]
    assert MEMORY_INDEX_NOTICE in output["unknowns"]
    assert output["answerability"] == "insufficient_evidence"
    assert output["delivered_content_tokens"] == 0
    assert output["compiled_content_tokens"] > 0
    assert output["memory_index_tokens"] > 0
    assert output["completion_contract"] == source["completion_contract"]
    assert output["output_usage"]["tokens_upper_bound"] == measure_output(output) <= limit


@pytest.mark.parametrize("protection", ["guardrail", "L0", "must_include", "constraint"])
def test_mandatory_source_is_never_truncated_or_replaced_with_index(protection: str) -> None:
    rule = {"id": "rule", "content": "不得删除持久数据。" * 1000}
    source = {"memories": [rule]}
    if protection == "guardrail":
        rule["type"] = "guardrail"
    elif protection == "L0":
        rule["layer"] = "L0"
    elif protection == "must_include":
        source["must_include"] = [{"id": "rule", "type": "memory"}]
    else:
        source = {"constraints": [rule], "memories": []}
    before = deepcopy(source)

    output = context_output(source, mode="compact", limit=2000)

    assert output["error"]["code"] == "OUTPUT_BUDGET_TOO_SMALL"
    assert "memory_index" not in output
    assert source == before
    assert measure_output(output) <= 2000


def test_compact_retains_warnings_conflicts_provenance_and_mode_fallback() -> None:
    source = personal_context()
    source["memories"] = source["memories"][1:]
    source["memories"][0]["intervention"] = {
        "action": "inject_with_warning",
        "include": True,
        "reason": "support_state:conflicting;authority:provisional",
    }
    source["context_policy"].update(
        {
            "requested_mode": "enforce",
            "fallback_reason": "context_policy_enforce_disabled",
        }
    )
    source["conflicts"] = [{"source_constraint_id": "rule", "reason": "Unresolved."}]
    source["preflight"] = {
        "decision": "blocked",
        "warnings": ["Need confirmation."],
        "requirements": ["Read complete rule."],
        "stale_warnings": ["Check source."],
        "unknowns": ["Deployment is unknown."],
        "diagnostic": "noise" * 3000,
    }
    source["answerability"] = "conflicted"

    output = context_output(source, mode="compact", limit=4500)

    assert output["answerability"] == "conflicted"
    assert output["conflicts"] == source["conflicts"]
    assert output["memories"][0]["intervention"] == source["memories"][0]["intervention"]
    assert output["context_policy"]["requested_mode"] == "enforce"
    assert output["context_policy"]["fallback_reason"] == "context_policy_enforce_disabled"
    assert output["preflight"] == {
        key: value for key, value in source["preflight"].items() if key != "diagnostic"
    }
    assert output["context_run_id"] == RUN_ID
    assert output["diagnostics"]["href"].endswith(RUN_ID)
    assert measure_output(output) <= 4500


def test_full_keeps_all_original_fields_and_adds_separate_delivery_accounting() -> None:
    source = personal_context()
    output = context_output(source, mode="full", limit=256)

    assert {key: output[key] for key in source} == source
    assert output["compiled_content_tokens"] == output["delivered_content_tokens"] > 0
    assert output["output_usage"]["limit"] is None
    assert output["output_usage"]["tokens_upper_bound"] == measure_output(output) > 256


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["complete", "index", "error"])
async def test_runtime_diagnostics_distinguish_compilation_delivery_and_references(
    monkeypatch,
    delivery: str,
) -> None:
    source = personal_context()
    if delivery == "index":
        source["memories"] = source["memories"][:1]
    if delivery == "error":
        source["memories"][0]["layer"] = "L0"
    selected = {"memories": [item["id"] for item in source["memories"]]}
    run = SimpleNamespace(
        trace={"selected_count": len(source["memories"])},
        selected=deepcopy(selected),
        token_used=2200,
        status="completed",
        error_code=None,
    )
    session = AsyncMock()
    session.get.return_value = run
    monkeypatch.setattr(
        "app.api.context_runtime._build_unified_context",
        AsyncMock(return_value=source),
    )

    output = await get_unified_context(
        UnifiedContextRequest(task="开发", output_mode="compact", max_output_tokens=2200),
        session,
        "user",
    )

    session.get.assert_awaited_once_with(ContextRun, UUID(RUN_ID))
    assert run.trace["compiled_selected"] == selected
    assert run.selected["memories"] == ([SHORT_ID] if delivery == "complete" else [])
    assert run.trace["referenced_memory_ids"] == ([LONG_ID] if delivery == "index" else [])
    assert run.trace["compiled_content_tokens"] == content_tokens(source) > 0
    assert run.trace["delivered_content_tokens"] == output.get("delivered_content_tokens", 0)
    assert run.trace["memory_index_tokens"] == output.get("memory_index_tokens", 0)
    assert run.token_used == 2200
    assert run.status == ("failed" if delivery == "error" else "completed")
    assert measure_output(output) <= 2200
