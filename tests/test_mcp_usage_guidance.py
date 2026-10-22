"""Keep capability, resource and prompt entry points on the same optional workflow."""

import asyncio
import json

import pytest

from echome_mcp.tools.capabilities import echome_capabilities, retrieval_workflow_prompt


@pytest.mark.parametrize("profile", ["core", "full"])
def test_guidance_does_not_require_a_memory_lifecycle_for_each_task(monkeypatch, profile):
    monkeypatch.setenv("ECHOME_MCP_PROFILE", profile)

    payload = json.loads(asyncio.run(echome_capabilities()))
    prompt = asyncio.run(echome_capabilities(format="prompt"))
    policy = payload["usage_policy"]

    assert policy["retrieval"] == "on_demand"
    assert policy["unmatched_project"] == "continue_without_project"
    assert policy["project_creation"] == "explicit_request_only"
    assert policy["outcome"] == "optional_when_evidence_is_clear"

    # Protect both client-facing guides from the former contradictory directions.
    guidance = json.dumps(payload) + prompt
    for instruction in (
        "At the end of every recorded",
        "close that recorded run exactly once",
        "Call echome_context first",
        "silently create on not_found",
        "Create silently after not_found",
        "call echome_project_preflight before material actions",
    ):
        assert instruction not in guidance
    assert "Reuse relevant context already available in the conversation" in prompt
    assert "Current user instructions and verified current evidence override historical memory" in prompt

    # The optional reporting tool remains discoverable for integrations using it.
    orientation = {entry["tool"]: entry for entry in payload["tool_groups"]["orientation"]}
    assert orientation["echome_context_outcome"]["mutates_state"] is True
    assert "Optional" in orientation["echome_context_outcome"]["when"]


@pytest.mark.parametrize("profile", ["core", "full"])
def test_on_demand_prompt_preserves_project_filter_and_profile_tools(monkeypatch, profile):
    monkeypatch.setenv("ECHOME_MCP_PROFILE", profile)

    prompt = retrieval_workflow_prompt(project_id="known-project")

    assert "Project filter: known-project." in prompt
    assert "echome_knowledge_read" in prompt
    assert "echome_scene_read" in prompt
    assert ("echome_search_summary" in prompt) is (profile == "full")
