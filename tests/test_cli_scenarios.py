"""CLI commands preserve scenario IDs and send validated JSON to Hub."""

import json

from typer.testing import CliRunner

from echome.commands import scenario as scenario_commands
from echome.main import app


def test_scenario_create_uses_json_definition_file(monkeypatch, tmp_path) -> None:
    calls: list[tuple] = []

    class FakeClient:
        def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"scenario": {"slug": "host-check"}}

    monkeypatch.setattr(scenario_commands, "HubClient", FakeClient)
    file = tmp_path / "scenario.json"
    file.write_text(json.dumps({"slug": "host-check", "definition": {"steps": ["check"]}}))

    result = CliRunner().invoke(app, ["scenario", "create", str(file)])

    assert result.exit_code == 0, result.output
    assert calls == [("POST", "", {"slug": "host-check", "definition": {"steps": ["check"]}}, None)]


def test_scenario_resolve_rejects_non_string_parameters() -> None:
    result = CliRunner().invoke(
        app,
        [
            "scenario",
            "resolve",
            "host-check",
            "--parameters",
            '{"target":42}',
        ],
    )
    assert result.exit_code != 0
    assert "string" in result.output.lower()


def test_scenario_bind_can_supply_target_inputs(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeClient:
        def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"item": {"scenario_slug": "host-check"}}

    monkeypatch.setattr(scenario_commands, "HubClient", FakeClient)
    result = CliRunner().invoke(
        app,
        [
            "scenario",
            "bind",
            "item-id",
            "host-check",
            "--revision",
            "3",
            "--reason",
            "Validated",
            "--parameters",
            '{"target":"host-a"}',
            "--environment",
            '{"os":"linux"}',
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "POST",
            "/items/item-id/bind",
            {
                "expected_revision": 3,
                "scenario_slug": "host-check",
                "version": None,
                "reason": "Validated",
                "parameters": {"target": "host-a"},
                "environment": {"os": "linux"},
            },
            None,
        )
    ]


def test_scenario_items_can_find_ongoing_case(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeClient:
        def scenario_request(self, method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"items": []}

    monkeypatch.setattr(scenario_commands, "HubClient", FakeClient)
    result = CliRunner().invoke(
        app,
        ["scenario", "items", "--query", "家庭网络", "--scenario", "home-network-readonly"],
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "GET",
            "/items",
            None,
            {
                "status": None,
                "mode": None,
                "query": "家庭网络",
                "scenario_slug": "home-network-readonly",
            },
        )
    ]
