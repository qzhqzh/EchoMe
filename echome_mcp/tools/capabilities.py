"""EchoMe MCP capability guide for agents."""

import json
from copy import deepcopy
from typing import Any

from echome_mcp import __version__
from echome_mcp.profiles import CORE_TOOL_NAMES, current_profile

CAPABILITIES: dict[str, Any] = {
    "service": "EchoMe MCP",
    "mcp_version": __version__,
    "capabilities_version": "echome.capabilities.v13",
    "context_schema_version": "echome.context.v1",
    "error_schema_version": "echome.error.v1",
    "purpose": "Personal memory and project context layer for AI agents.",
    "recommended_start": "echome_capabilities",
    "default_context_tool": "echome_context",
    "usage_policy": {
        "retrieval": "on_demand",
        "trigger": "Missing historical context would materially change the answer or action, or the user explicitly requests recall.",
        "reuse": "Reuse relevant context already available in the conversation; retrieve again only for a new gap, conflict, or freshness concern.",
        "unmatched_project": "continue_without_project",
        "project_creation": "explicit_request_only",
        "outcome": "optional_when_evidence_is_clear",
        "precedence": "Current user instructions and verified current evidence take precedence over historical memory.",
    },
    "knowledge_workflow": [
        {"step": "discover", "tool": "echome_knowledge_read", "when": "For knowledge projects/questions, read schema once, list by kind/search, then request context for the selected stable UUID. Follow omitted_fields and next_offset."},
        {"step": "maintain", "tool": "echome_knowledge_write", "when": "Save coarse independent knowledge, exact source/usage versions and actual outputs. Propose risky semantic edits as review records; never self-approve."},
    ],
    "scenario_workflow": [
        {"step": "read_knowledge", "tool": "echome_scene_read",
         "when": "A user names a recurring scene; read its dated facts, observations, active SOPs, cautions and current work before acting."},
        {"step": "maintain_knowledge", "tool": "echome_scene_write",
         "when": "After checking source evidence, add atomic items individually or in one batch, or correct one exact revision; keep untested operations in work, not SOP."},
        {"step": "resolve", "tool": "echome_scenario_resolve",
         "when": "The user explicitly names a published executable procedure, after reading any related scene knowledge."},
        {"step": "resume", "tool": "echome_scenario_item",
         "when": "The user wants to continue work across chats; list with data.query or data.scenario_slug, then get its pinned version or standalone plan and state."},
        {"step": "execute", "tool": "echome_scenario_run",
         "when": "Before actual execution, claim a lease; then finish with evidence and the next check time."},
        {"step": "maintain", "tool": "echome_scenario_catalog",
         "when": "Save a draft, then publish only after validation evidence exists."},
    ],
    "card_workflow": [
        {"step": "find", "tool": "echome_card_read",
         "when": "When a reusable habit, procedure, or knowledge claim may help; list by kind or query, then get the relevant card."},
        {"step": "maintain", "tool": "echome_card_write",
         "when": "After a user instruction or concrete result supports a durable card; reuse an existing card, create in ai_review, or edit selected fields with its current updated_at."},
    ],
    "default_retrieval_workflow": [
        {
            "step": "discover",
            "tool": "echome_search_summary",
            "when": "Historical context is needed and a broad set of candidate memories needs browsing; skip when current context is sufficient.",
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
            "when": "When missing project history matters, send known identity signals. If unresolved, continue from current evidence without creating a project or requiring user confirmation.",
        },
        {
            "step": "maintain_identity",
            "tool": "echome_update_project_git_identity",
            "when": "Only when project registration or identity maintenance is requested. Explicit primary Git remote mutations remain preview-confirmed.",
        },
        {
            "step": "preflight",
            "tool": "echome_project_preflight",
            "when": "When a relevant past failure or validation requirement is missing from current context; returns evidence-backed warnings without blocking work.",
        },
        {
            "step": "context",
            "tool": "echome_project_context",
            "when": "When project constraints or historical evidence are missing; choose local, overview, or impact mode and pass changed paths. Reuse an existing context pack when sufficient.",
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
        "knowledge": [
            {"tool": "echome_knowledge_read", "when": "Read knowledge schema, project/question context, versioned Pages, evidence, exact queries or discovery results.", "mutates_state": False},
            {"tool": "echome_knowledge_write", "when": "Save coarse reusable knowledge, Pages, sources, usages, real outputs or review proposals. Never self-approve a consequential change.", "mutates_state": True},
        ],
        "cards": [
            {"tool": "echome_card_read", "when": "Browse the card library or read one card with its scope and revision.", "mutates_state": False},
            {"tool": "echome_card_write", "when": "Create an AI-reviewed card or revise named fields of a card using its current revision and a concrete basis.", "mutates_state": True, "default_status": "ai_review_on_create"},
        ],
        "scenarios": [
            {"tool": "echome_scene_read", "when": "Read a named scene document, atomic items, and correction history.", "mutates_state": False},
            {"tool": "echome_scene_write", "when": "Create a scene, add or correct sourced items, or publish a repeatedly validated SOP.", "mutates_state": True},
            {"tool": "echome_scenario_resolve", "when": "Resolve a user-named scenario without guessing or executing.", "mutates_state": False},
            {"tool": "echome_scenario_catalog", "when": "Create and version a scenario; publish only with validation evidence.", "mutates_state": True},
            {"tool": "echome_scenario_item", "when": "Create or resume a standalone or pinned item; pause, complete, upgrade, or explicitly bind it.", "mutates_state": True},
            {"tool": "echome_scenario_run", "when": "Claim and finish an execution attempt or inspect its history.", "mutates_state": True},
        ],
        "orientation": [
            {
                "tool": "echome_capabilities",
                "when": "First contact with EchoMe MCP, or when unsure which EchoMe tool to use.",
                "mutates_state": False,
            },
            {
                "tool": "echome_context",
                "when": "Use when historical preferences or project context affect the task; routes automatically and returns answerability, reliability interventions, and runtime metadata.",
                "mutates_state": False,
            },
            {
                "tool": "echome_runtime_health",
                "when": "Diagnose runtime state; request policy readiness before considering any enforce canary.",
                "mutates_state": False,
            },
            {
                "tool": "echome_context_outcome",
                "when": "Optional: append an evidenced usefulness or correction result for a recorded non-shadow run. Skip when usefulness is unknown; no routine no_signal report or user rating request is needed.",
                "mutates_state": True,
            },
        ],
        "retrieval": [
            {
                "tool": "echome_search_summary",
                "when": "Browse candidate memories when missing historical context matters and the query is broad or uncertain.",
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
                "when": "Retrieve missing project constraints, artifact evidence, or scoped memories when they would change the task.",
                "mutates_state": False,
            },
            {
                "tool": "echome_project_impact",
                "when": "Before changing requirements, architecture, APIs, code paths, or tests; returns the affected local constraint graph.",
                "mutates_state": False,
            },
            {
                "tool": "echome_project_preflight",
                "when": "Recall relevant past failures or validation requirements that are not already known; warnings do not block the action.",
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
                "when": "Only when the user requests project registration or identity maintenance. Retrieval misses do not authorize creation; resolve ambiguity before any write.",
                "mutates_state": True,
                "requires_confirmation": False,
                "idempotent": True,
            },
            {
                "tool": "echome_update_project_git_identity",
                "when": "For an existing canonical project whose confirmed Git remote or alias is missing; preview with confirmed=false before applying.",
                "mutates_state": True,
                "requires_confirmation": True,
                "idempotent": True,
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
        "Scene knowledge is text-first. Read the named scene with echome_scene_read before adding or correcting; preserve each fact, observation and caution as one sourced item.",
        "A procedure is not a formal SOP until repeated independent effective runs support it. Keep one-off or untested actions in the current work record.",
        "When new evidence conflicts with a current scene fact, mark it needs_review or correct that exact revision with a reason and source; never silently overwrite unrelated items.",
        "When execution of a published procedure is requested, resolve that executable scenario before planning. A ready_for_manual_checks result still requires applicability review and normal task authorization.",
        "EchoMe stores scenario state and due times but does not execute tasks or schedule a worker; a connected executor must claim, run, and finish each check.",
        "Use echome_context when historical preferences or project conventions materially affect the task; do not query it mechanically for every request.",
        "When historical workflow or project conventions matter, retrieve relevant context before assuming them.",
        "When historical retrieval is needed, use summary-first for broad questions; top_k semantic search does not guarantee complete project context.",
        "Use graph explanation after reading a key memory if the task depends on its correctness or freshness.",
        "Ask for or record feedback only when a memory clearly influenced the task, the user corrected it, or the memory appears outdated/conflicting; do not interrupt every turn.",
        "Archived/deprecated memories should not be used as active facts, but may be useful as provenance through graph tools.",
        "Writing tools should be used only for durable, reusable memories; do not save secrets or one-off temporary facts.",
        "Read related cards before creating one. Card creation uses ai_review (already retrievable); edits require the latest updated_at and preserve unrelated content.",
        "Use memory tools for user behavior and working preferences; use project-intelligence tools for requirements, implementation constraints, evidence, and impact analysis.",
        "Use project context and preflight only to fill a relevant gap in historical constraints or failure evidence. Reuse sufficient context; do not turn retrieval into a prerequisite for each edit or test.",
        "Project events and inferred constraints remain proposals/evidence. They do not silently become active constraints or mutate memories.",
        "Use echome_reflect_prepare before echome_reflect_submit. Every derived claim must cite a prepared source, and a changed source fingerprint requires preparing again.",
        "Outcome reporting is optional when usefulness or a correction is supported by evidence. Use the returned run ID and idempotency key; skip unknown outcomes rather than routinely sending no_signal. Never infer usefulness from task completion alone.",
        "Context reliability defaults to shadow mode: decisions are observable but source memories and constraints are never rewritten. Enforce mode also requires an explicit Hub feature flag.",
        "Before any enforce canary, call echome_runtime_health with include_policy_readiness=true. eligible_for_canary never enables enforce automatically.",
        "Unknown or ambiguous projects must not block ordinary work or trigger automatic project creation. Continue from current evidence; ask about identity only when a requested project-specific write or decision depends on it.",
        "Current user instructions and verified current evidence override historical memory. Treat conflicts as information to check, never as permission to constrain the current task.",
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
            "when": "When missing historical preferences or project context would change the task; reuse sufficient context already in the conversation.",
        },
        {
            "step": "explain",
            "tool": "echome_memory_explain",
            "when": "Inspect provenance or freshness when a key memory has conflicting or uncertain evidence.",
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
            "when": "Pass project hints and changed paths when missing project history matters; continue from current evidence if identity is unresolved.",
        },
        {
            "step": "create",
            "tool": "echome_create_project",
            "when": "Only when project registration or identity maintenance is requested; never create solely because retrieval found no project.",
        },
    ]
    payload["scenario_workflow"] = CAPABILITIES["scenario_workflow"]
    payload["card_workflow"] = CAPABILITIES["card_workflow"]
    payload["knowledge_workflow"] = CAPABILITIES["knowledge_workflow"]
    payload["tool_groups"] = {
        group: [entry for entry in entries if entry["tool"] in CORE_TOOL_NAMES]
        for group, entries in payload["tool_groups"].items()
    }
    payload["tool_groups"] = {
        group: entries for group, entries in payload["tool_groups"].items() if entries
    }
    payload["rules"] = [
        "Read a named scene with echome_scene_read before using its facts or SOPs. Historical observations are not current measurements.",
        "Use echome_scene_write to add atomic sourced entries or correct an exact revision. Keep untested actions in work; formal SOP requires repeated independent evidence.",
        "When execution of a published procedure is requested, resolve it before choosing steps. Check applicability and current authorization before executing.",
        "Continuous items need an external scheduler; EchoMe stores due times, leases, status, and run history.",
        "Use echome_context when historical preferences or project context matter; do not call it mechanically for every request.",
        "Use echome_memory_explain when a key memory may be stale, replaced, or conflicting.",
        "Archived/deprecated memories are provenance, not active facts.",
        "Use echome_remember only for durable context and never store secrets.",
        "Read related cards before creating or editing one. Only record reusable, supported guidance; ai_review cards are already searchable, and edits require the latest revision.",
        "Outcome reporting is optional. Submit only a clear usefulness or correction signal with the returned run ID and idempotency key; skip unknown outcomes without a no_signal ritual or user rating request.",
        "Record memory feedback only when usefulness or a correction is clear; missing feedback is unknown.",
        "Continue ordinary work when a project is unknown or ambiguous. Register projects only when requested; ask about identity only if a project-specific write or decision depends on it.",
        "Reuse sufficient context already available in the conversation. Current user instructions and verified current evidence override historical memory.",
    ]
    return payload


def capabilities_json() -> str:
    """Return the agent-facing capability guide as JSON."""
    return json.dumps(capabilities_payload(), ensure_ascii=False, indent=2)


def retrieval_workflow_prompt(project_id: str | None = None) -> str:
    """Return an on-demand guide without a mandatory per-task lifecycle."""
    project_hint = f" Project filter: {project_id}." if project_id else ""
    guide = (
        "Use EchoMe only when missing history would materially change the task or the user requests recall."
        f"{project_hint}\n\n"
        "Reuse relevant context already available in the conversation. General questions, self-contained edits, "
        "and continued work with sufficient context do not need another memory check.\n"
        "When retrieval is needed, call echome_context with the task and known project hints/changed paths. "
        "For a named scene, use echome_scene_read; for structured knowledge, use echome_knowledge_read. "
        "Read only relevant results and follow up only for a concrete gap, conflict, or freshness concern.\n"
        "No matches, unavailable tools, or unresolved project identity are reasons to continue from current "
        "evidence, not to ask the user to confirm memory or automatically register a project. "
        "Use echome_create_project only when registration or identity maintenance is requested. "
        "Primary Git remote mutations still require preview and explicit confirmation.\n"
        "Use echome_memory_explain when provenance or freshness of a key memory is uncertain. "
        "Current user instructions and verified current evidence override historical memory; "
        "archived/deprecated memories are provenance only.\n"
        "Outcome reporting is optional: use echome_context_outcome with the returned run ID and idempotency key "
        "only for an evidenced usefulness or correction signal. Skip unknown outcomes; no routine no_signal "
        "report or user rating request is needed. Record individual memory feedback only when its signal is clear.\n"
        "Save only durable reusable context with echome_remember. Read related cards before creating or "
        "editing supported guidance with echome_card_write; never store secrets. "
        "Infer needed tools without requiring the user to manage memory calls."
    )
    if current_profile() == "full":
        guide += (
            "\n\nFor broader historical discovery, use echome_search_summary and read selected UUIDs with "
            "echome_get_memories instead of loading everything. Use project preflight, impact, and graph tools "
            "only when an unresolved task-specific issue needs them. For durable cross-source synthesis, "
            "prepare evidence with echome_reflect_prepare before echome_reflect_submit."
        )
    return guide


async def echome_capabilities(format: str = "json") -> str:
    """Return EchoMe MCP tool groups and recommended workflows."""
    if format == "prompt":
        return retrieval_workflow_prompt()
    return capabilities_json()
