"""CLI sync command safety tests."""

from typer.testing import CliRunner

from echome.main import app

runner = CliRunner()


def test_push_does_not_report_success_without_a_local_vault_implementation() -> None:
    result = runner.invoke(app, ["push"])

    assert result.exit_code == 2
    assert "not implemented" in result.output
    assert "Push complete" not in result.output


def test_pull_does_not_report_success_without_a_local_vault_implementation() -> None:
    result = runner.invoke(app, ["pull"])

    assert result.exit_code == 2
    assert "not implemented" in result.output
    assert "Pull complete" not in result.output
