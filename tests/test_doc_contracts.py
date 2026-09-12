"""Drift detection must fail on invalid examples and ignore historical snippets."""

import pytest
from click import NoSuchOption

from scripts.check_doc_contracts import check_command, check_links, check_mcp_schema


@pytest.mark.parametrize("command", ["echome", "echome mcp", "echome mcp serve"])
def test_help_is_a_valid_documented_command(command):
    check_command(f"{command} --help")


def test_invalid_command_and_option_are_rejected():
    with pytest.raises(ValueError, match="unknown CLI command"):
        check_command("echome absent-command")
    with pytest.raises(NoSuchOption):
        check_command("echome mcp serve --not-an-option")


def test_enum_required_and_unknown_parameter_drift_are_rejected():
    actual = {
        "type": "object",
        "properties": {"type": {"enum": ["stack", "style"]}},
        "required": ["type"],
    }
    with pytest.raises(ValueError, match="enum differs"):
        check_mcp_schema({"properties": {"type": {"enum": ["tech", "style"]}}}, actual)
    with pytest.raises(ValueError, match="not in"):
        check_mcp_schema({"properties": {"project_id": {"type": "string"}}}, actual)
    with pytest.raises(ValueError, match="required differs"):
        check_mcp_schema({"required": []}, actual)


def test_relative_links_are_checked_outside_example_fences(tmp_path):
    path = tmp_path / "guide.md"
    assert check_links(path, "[missing](absent.md)")
    assert check_links(path, "```markdown\n[example](absent.md)\n```\n") == []
