"""Rendered agent instructions stay compatible with the default MCP profile."""

from app.services.renderer import MCP_INSTRUCTION


def test_default_rendered_instruction_uses_core_tools() -> None:
    assert "`echome_context`" in MCP_INSTRUCTION
    assert "`echome_memory_explain`" in MCP_INSTRUCTION
    assert "`echome_remember`" in MCP_INSTRUCTION
    assert "`echome_search_summary`" not in MCP_INSTRUCTION
    assert "`echome_get_memories`" not in MCP_INSTRUCTION
    assert "`echome_list_projects`" not in MCP_INSTRUCTION
