"""New MCP registrations select the compact profile explicitly."""

from echome.commands.init import _upsert_codex_config


def test_codex_registration_sets_core_profile(tmp_path) -> None:
    config = tmp_path / "config.toml"

    _upsert_codex_config(config)

    content = config.read_text()
    assert '[mcp_servers.echome]' in content
    assert 'env = { ECHOME_MCP_PROFILE = "core" }' in content
