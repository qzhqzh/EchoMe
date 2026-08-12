"""EchoMe MCP capability guide for agents."""

import json
from typing import Any

CAPABILITIES: dict[str, Any] = {
    "service": "EchoMe MCP",
    "purpose": "Personal memory and project context layer for AI agents.",
    "recommended_start": "echome_capabilities",
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
            }
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
                "when": "List all eligible memories for manual Memory Sleep planning.",
                "mutates_state": False,
            },
            {
                "tool": "echome_sleep_submit_proposal",
                "when": "Submit a user/AI approved JSON sleep proposal.",
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
        "Do not assume user workflow or project conventions when EchoMe is connected; retrieve relevant memories first.",
        "Use summary-first for broad questions; avoid relying on top_k=5 semantic search for complete project context.",
        "Use graph explanation after reading a key memory if the task depends on its correctness or freshness.",
        "Ask for or record feedback only when a memory clearly influenced the task, the user corrected it, or the memory appears outdated/conflicting; do not interrupt every turn.",
        "Archived/deprecated memories should not be used as active facts, but may be useful as provenance through graph tools.",
        "Writing tools should be used only for durable, reusable memories; do not save secrets or one-off temporary facts.",
        "Use memory tools for user behavior and working preferences; use project-intelligence tools for requirements, implementation constraints, evidence, and impact analysis.",
        "For project work, call echome_project_preflight before material actions and echome_project_context for the evidence-first context pack; do not ask the user to choose between memory and graph search.",
        "Project events and inferred constraints remain proposals/evidence. They do not silently become active constraints or mutate memories.",
    ],
}


def capabilities_json() -> str:
    """Return the agent-facing capability guide as JSON."""
    return json.dumps(CAPABILITIES, ensure_ascii=False, indent=2)


def retrieval_workflow_prompt(project_id: str | None = None) -> str:
    """Return a reusable prompt for EchoMe retrieval."""
    project_hint = f" Project filter: {project_id}." if project_id else ""
    return (
        "Use EchoMe MCP as the memory and project-context layer."
        f"{project_hint}\n\n"
        "For implementation work with a known project, call echome_project_preflight before material actions, "
        "then call echome_project_context with the task and changed paths. Use local mode for focused work, "
        "overview for orientation, and impact for propagation analysis.\n\n"
        "Default workflow:\n"
        "1. For broad tasks, call echome_search_summary with a concise query and optional project_id.\n"
        "2. Select only relevant UUIDs and call echome_get_memories.\n"
        "3. If a selected memory is important for a project decision, deployment, version, historical assumption, "
        "or could be stale, call echome_memory_explain on that memory.\n"
        "4. If neighboring context matters, call echome_memory_neighbors with include_inactive=true for provenance.\n"
        "5. At task end, if memory usefulness is clear or the user corrected a memory, call echome_memory_feedback or echome_memory_feedback_batch.\n"
        "6. Treat archived/deprecated memories as non-active facts unless graph provenance explains why they matter.\n"
        "7. Use echome_remember only for durable preferences, decisions, conventions, or reusable project context.\n\n"
        "Do not ask the user to remember tool names. Infer the needed EchoMe tools from the task."
    )


async def echome_capabilities(format: str = "json") -> str:
    """Return EchoMe MCP tool groups and recommended workflows."""
    if format == "prompt":
        return retrieval_workflow_prompt()
    return capabilities_json()
