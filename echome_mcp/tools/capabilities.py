"""EchoMe MCP capability guide for agents."""

import json
from copy import deepcopy
from typing import Any

from echome_mcp import __version__
from echome_mcp.profiles import CORE_TOOL_NAMES, current_profile

CAPABILITIES: dict[str, Any] = {
    "service": "EchoMe MCP",
    "mcp_version": __version__,
    "capabilities_version": "echome.capabilities.v7",
    "context_schema_version": "echome.context.v1",
    "error_schema_version": "echome.error.v1",
    "purpose": "Personal memory and project context layer for AI agents.",
    "recommended_start": "echome_capabilities",
    "default_context_tool": "echome_context",
    "default_retrieval_workflow": [
        {
            "step": "discover",
            "tool": "echome_search_summary",
            "when": "Broad tasks, project work, user preferences, historical decisions, or many possible memories.",
        },
        {
            "step": "read",
            "tool": "echome_get_memories",
            "when": "Read only the selected UUIDs from the summary index.",
        },
        {
            "step": "explain",
            "tool": "echome_memory_explain",
            "when": "Before relying on a key memory for project decisions, historical assumptions, versions, deployments, or potentially stale information.",
        },
        {
            "step": "feedback",
            "tool": "echome_memory_feedback",
            "when": "After the task, record clear usefulness signals for memories that were helpful, important, outdated, conflicting, wrong, or irrelevant.",
        },
    ],
    "project_workflow": [
        {
            "step": "resolve",
            "tool": "echome_context",
            "when": "Send all known project identity signals. Follow project_resolution retry actions instead of stopping after an unmatched hint.",
        },
        {
            "step": "preflight",
            "tool": "echome_project_preflight",
            "when": "Before a material edit, test, commit, migration, or deploy; returns evidence-backed warnings only.",
        },
        {
            "step": "context",
            "tool": "echome_project_context",
            "when": "Default project task entry; choose local, overview, or impact mode and pass changed paths.",
        },
        {
            "step": "impact",
            "tool": "echome_project_impact",
            "when": "When a requirement, API, architecture, code, or test change may propagate through constraints.",
        },
        {
            "step": "reflect_prepare",
            "tool": "echome_reflect_prepare",
            "when": "When cross-source evidence is stable enough to justify a durable summary or mental model.",
        },
        {
            "step": "reflect_submit",
            "tool": "echome_reflect_submit",
            "when": "After prepare, submit only claims that cite the returned source IDs and unchanged fingerprint.",
        },
        {
            "step": "record",
            "tool": "echome_project_event_append",
            "when": "After a durable failure, fix, decision, test result, or deploy; link source evidence when available.",
        },
    ],
    "tool_groups": {
        "orientation": [
            {
                "tool": "echome_capabilities",
                "when": "First contact with EchoMe MCP, or when unsure which EchoMe tool to use.",
                "mutates_state": False,
            },
            {
                "tool": "echome_context",
                "when": "Default single entry for personal or project work; routes automatically and returns answerability, reliability interventions, and runtime metadata.",
                "mutates_state": False,
            },
            {
                "tool": "echome_runtime_health",
                "when": "Diagnose runtime state; request policy readiness before considering any enforce canary.",
                "mutates_state": False,
            },
            {
                "tool": "echome_context_outcome",
                "when": "At the end of every recorded non-shadow context run. Use no_signal when usefulness cannot be judged.",
                "mutates_state": True,
            },
        ],
        "retrieval": [
            {
                "tool": "echome_search_summary",
                "when": "Default first retrieval tool for broad or uncertain questions.",
                "mutates_state": False,
            },
            {
                "tool": "echome_get_memories",
                "when": "Fetch full content for selected UUIDs from summary results.",
                "mutates_state": False,
            },
            {
                "tool": "echome_search",
                "when": "Narrow, explicit semantic search; not ideal for broad project orientation.",
                "mutates_state": False,
            },
            {
                "tool": "echome_get",
                "when": "Fetch one known memory UUID.",
                "mutates_state": False,
            },
        ],
        "graph_reasoning": [
            {
                "tool": "echome_memory_explain",
                "when": "Check provenance, replacement links, adjacent memories, and temporal reliability for one memory.",
                "mutates_state": False,
            },
            {
                "tool": "echome_memory_neighbors",
                "when": "Expand a local graph around a key memory to build stable project context.",
                "mutates_state": False,
            },
            {
                "tool": "echome_temporal_candidates",
                "when": "Audit memories that may need verification; long inactivity alone is not stale.",
                "mutates_state": False,
            },
        ],
        "project_intelligence": [
            {
                "tool": "echome_project_context",
                "when": "Default entry for project implementation tasks; combines project constraints, artifact evidence, and scoped memories.",
                "mutates_state": False,
            },
            {
                "tool": "echome_project_impact",
                "when": "Before changing requirements, architecture, APIs, code paths, or tests; returns the affected local constraint graph.",
                "mutates_state": False,
            },
            {
                "tool": "echome_project_preflight",
                "when": "Before project actions; recalls evidence-backed failures and validation requirements without blocking the action.",
                "mutates_state": False,
            },
            {
                "tool": "echome_reflect_prepare",
                "when": "Prepare a complete source pack and freshness fingerprint before synthesizing a durable project view.",
                "mutates_state": False,
            },
            {
                "tool": "echome_reflect_submit",
                "when": "Persist a prepared reflection whose claims cite exact source IDs; stale fingerprints are rejected.",
                "mutates_state": True,
                "source_mutation": False,
                "default_status": "current_derived_view",
            },
            {
                "tool": "echome_project_event_append",
                "when": "Append a durable project episode. It never promotes itself to an active constraint.",
                "mutates_state": True,
                "default_status": "append_only_event",
            },
            {
                "tool": "echome_project_index",
                "when": "Synchronize local project documents and code metadata using a hash manifest before uploading changed content.",
                "mutates_state": True,
            },
            {
                "tool": "echome_constraint_propose",
                "when": "Record an inferred project constraint as proposed without changing personal memory behavior.",
                "mutates_state": True,
                "default_status": "proposed",
            },
        ],
        "project_identity": [
            {
                "tool": "echome_create_project",
                "when": "Only after echome_context returns project_resolution.status=not_found and the user explicitly confirms this is a new project.",
                "mutates_state": True,
            },
        ],
        "write": [
            {
                "tool": "echome_memory_feedback",
                "when": "Append a lightweight usefulness signal after a memory was used; does not change memory status.",
                "mutates_state": True,
                "status_mutation": False,
            },
            {
                "tool": "echome_memory_feedback_batch",
                "when": "Append feedback for several memories at task end; does not change memory status.",
                "mutates_state": True,
                "status_mutation": False,
            },
            {
                "tool": "echome_remember",
                "when": "Save durable preferences, decisions, conventions, or reusable project context.",
                "mutates_state": True,
                "default_status": "ai_review",
            },
        ],
        "sleep": [
            {
                "tool": "echome_sleep_candidates",
                "when": "List all eligible memories and the latest v2 planning contract for manual Memory Sleep planning.",
                "mutates_state": False,
            },
            {
                "tool": "echome_sleep_submit_proposal",
                "when": "Submit a JSON sleep proposal; v2 receives server-owned before/after simulation results.",
                "mutates_state": True,
            },
            {
                "tool": "echome_sleep_apply",
                "when": "Apply an approved sleep session proposal.",
                "mutates_state": True,
            },
        ],
    },
    "rules": [
        "Use echome_context as the default initial call; use specialized tools only when its conflicts, unknowns, or recommended actions require focused follow-up.",
        "Do not assume user workflow or project conventions when EchoMe is connected; retrieve relevant memories first.",
        "Use summary-first for broad questions; avoid relying on top_k=5 semantic search for complete project context.",
        "Use graph explanation after reading a key memory if the task depends on its correctness or freshness.",
        "Ask for or record feedback only when a memory clearly influenced the task, the user corrected it, or the memory appears outdated/conflicting; do not interrupt every turn.",
        "Archived/deprecated memories should not be used as active facts, but may be useful as provenance through graph tools.",
        "Writing tools should be used only for durable, reusable memories; do not save secrets or one-off temporary facts.",
        "Use memory tools for user behavior and working preferences; use project-intelligence tools for requirements, implementation constraints, evidence, and impact analysis.",
        "For project work, call echome_project_preflight before material actions and echome_project_context for the evidence-first context pack; do not ask the user to choose between memory and graph search.",
        "Project events and inferred constraints remain proposals/evidence. They do not silently become active constraints or mutate memories.",
        "Use echome_reflect_prepare before echome_reflect_submit. Every derived claim must cite a prepared source, and a changed source fingerprint requires preparing again.",
        "Follow the completion_contract returned by a recorded non-shadow context run. Outcomes are append-only; use no_signal instead of inventing success or failure, and set policy_effect only when explicit.",
        "Context reliability defaults to shadow mode: decisions are observable but source memories and constraints are never rewritten. Enforce mode also requires an explicit Hub feature flag.",
        "Before any enforce canary, call echome_runtime_health with include_policy_readiness=true. eligible_for_canary never enables enforce automatically.",
        "When project_resolution requires action, retry with a returned canonical ID; create a project only after status=not_found and explicit user confirmation.",
    ],
}


def capabilities_payload() -> dict[str, Any]:
    """Build a guide that only advertises tools available in the active profile."""
    payload = deepcopy(CAPABILITIES)
    profile = current_profile()
    payload["profile"] = profile
    if profile == "full":
        payload["available_tools"] = "all"
        return payload

    payload["available_tools"] = sorted(CORE_TOOL_NAMES)
    payload["profile_note"] = (
        "Set ECHOME_MCP_PROFILE=full and restart the client to expose specialized tools."
    )
    payload["default_retrieval_workflow"] = [
        {
            "step": "context",
            "tool": "echome_context",
            "when": "Default entry for personal or project work; returns relevant full context.",
        },
        {
            "step": "explain",
            "tool": "echome_memory_explain",
            "when": "Inspect provenance and temporal reliability before relying on a key memory.",
        },
        {
            "step": "feedback",
            "tool": "echome_memory_feedback",
            "when": "Record a clear usefulness or correction signal after the task.",
        },
    ]
    payload["project_workflow"] = [
        {
            "step": "context",
            "tool": "echome_context",
            "when": "Pass project hints and changed paths when project impact matters; follow structured retry actions when identity is unresolved.",
        },
        {
            "step": "create",
            "tool": "echome_create_project",
            "when": "Only after project_resolution.status=not_found and explicit user confirmation.",
        },
    ]
    payload["tool_groups"] = {
        group: [entry for entry in entries if entry["tool"] in CORE_TOOL_NAMES]
        for group, entries in payload["tool_groups"].items()
    }
    payload["tool_groups"] = {
        group: entries for group, entries in payload["tool_groups"].items() if entries
    }
    payload["rules"] = [
        "Use echome_context as the default initial call for personal and project work.",
        "Use echome_memory_explain when a key memory may be stale, replaced, or conflicting.",
        "Archived/deprecated memories are provenance, not active facts.",
        "Use echome_remember only for durable context and never store secrets.",
        "When echome_context returns a completion_contract, close that recorded run exactly once; use no_signal when usefulness is unknown.",
        "Record memory feedback only when usefulness or a correction is clear; missing feedback is unknown.",
        "If project resolution is ambiguous, retry echome_context with a returned canonical ID. Create only after not_found and explicit confirmation.",
    ]
    return payload


def capabilities_json() -> str:
    """Return the agent-facing capability guide as JSON."""
    return json.dumps(capabilities_payload(), ensure_ascii=False, indent=2)


def retrieval_workflow_prompt(project_id: str | None = None) -> str:
    """Return a reusable prompt for EchoMe retrieval."""
    project_hint = f" Project filter: {project_id}." if project_id else ""
    if current_profile() == "core":
        return (
            "Use EchoMe MCP as the memory and project-context layer."
            f"{project_hint}\n\n"
            "Call echome_context first with the current task, project hint, and changed paths when known. "
            "If it returns project_resolution, retry with a candidate canonical ID; call echome_create_project "
            "only after status=not_found and explicit user confirmation. "
            "Use echome_memory_explain before relying on a key memory whose provenance or freshness matters. "
            "When echome_context returns a completion_contract, call echome_context_outcome exactly once "
            "at task end and use no_signal when usefulness is unknown. Record memory feedback only when its "
            "signal is clear. "
            "Use echome_remember only for durable, reusable context and never store secrets. "
            "Do not ask the user to remember tool names; infer the needed EchoMe call from the task."
        )
    return (
        "Use EchoMe MCP as the memory and project-context layer."
        f"{project_hint}\n\n"
        "Start with echome_context for personal or project work. It infers the current Git remote when possible, "
        "resolves canonical project aliases, and combines project preflight with context compilation. Use the "
        "specialized project or graph tools only when the returned conflicts, unknowns, or recommended actions "
        "require focused follow-up.\n\n"
        "Default workflow:\n"
        "1. For broad tasks, call echome_search_summary with a concise query and optional project_id.\n"
        "2. Select only relevant UUIDs and call echome_get_memories.\n"
        "3. If a selected memory is important for a project decision, deployment, version, historical assumption, "
        "or could be stale, call echome_memory_explain on that memory.\n"
        "4. If neighboring context matters, call echome_memory_neighbors with include_inactive=true for provenance.\n"
        "5. At task end, follow completion_contract and call echome_context_outcome once. Use its idempotency key; report no_signal when usefulness is unknown and set policy_effect only with explicit evidence.\n"
        "6. If individual memory usefulness is clear or the user corrected a memory, call echome_memory_feedback or echome_memory_feedback_batch.\n"
        "7. Treat archived/deprecated memories as non-active facts unless graph provenance explains why they matter.\n"
        "8. Use echome_remember only for durable preferences, decisions, conventions, or reusable project context.\n\n"
        "9. When durable cross-source synthesis would help future project work, call echome_reflect_prepare, "
        "build claims only from its evidence IDs, then call echome_reflect_submit with the unchanged source watermark.\n\n"
        "Do not ask the user to remember tool names. Infer the needed EchoMe tools from the task."
    )


async def echome_capabilities(format: str = "json") -> str:
    """Return EchoMe MCP tool groups and recommended workflows."""
    if format == "prompt":
        return retrieval_workflow_prompt()
    return capabilities_json()
