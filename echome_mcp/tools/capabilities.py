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
            }
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
