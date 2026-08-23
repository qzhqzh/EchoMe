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
        "echome_memory_feedback",
        "echome_memory_feedback_batch",
    }
)


def current_profile() -> str:
    """Preserve legacy full installs; new installers write an explicit core profile."""
    return "core" if os.getenv("ECHOME_MCP_PROFILE", "full").lower() == "core" else "full"
