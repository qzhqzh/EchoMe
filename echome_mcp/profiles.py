"""MCP tool-surface profiles."""

import os

CORE_TOOL_NAMES = frozenset(
    {
        "echome_capabilities",
        "echome_context",
        "echome_runtime_health",
        "echome_context_outcome",
        "echome_memory_explain",
        "echome_remember",
        "echome_card_read",
        "echome_card_write",
        "echome_create_project",
        "echome_update_project_git_identity",
        "echome_memory_feedback",
        "echome_memory_feedback_batch",
        "echome_scenario_resolve",
        "echome_scenario_catalog",
        "echome_scenario_item",
        "echome_scenario_run",
        "echome_scene_read",
        "echome_scene_write",
        "echome_knowledge_read",
        "echome_knowledge_write",
    }
)


def current_profile() -> str:
    """Preserve legacy full installs; new installers write an explicit core profile."""
    return "core" if os.getenv("ECHOME_MCP_PROFILE", "full").lower() == "core" else "full"
