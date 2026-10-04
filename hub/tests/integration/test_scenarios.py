"""Scenario lifecycle against an isolated disposable PostgreSQL schema."""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User


def _definition(step: str = "Check current state") -> dict:
    return {
        "applicability": "Use for the named Linux host after confirming its identity.",
        "exclusions": "Do not use for a different host or network topology.",
        "input_fields": [
            {"name": "target", "description": "Host alias", "required": True, "secret": False}
        ],
        "required_environment": {"os": "linux"},
        "steps": [step],
        "verification": ["Compare observed status with the expected result"],
        "recovery": ["Stop and report an inconclusive check"],
        "execution_ref": None,
        "source_refs": [],
    }


async def _published_scenario(api, slug: str = "host-check") -> dict:
    created = await api.post(
        "scenarios",
        json={
            "slug": slug,
            "title": "Host check",
            "summary": "Check a known host repeatedly",
            "definition": _definition(),
        },
    )
    assert created.status_code == 201, created.text
    published = await api.post(
        f"scenarios/catalog/{slug}/versions/1/publish",
        json={"validation_evidence": "Dry run on a disposable host passed"},
    )
    assert published.status_code == 200, published.text
    return created.json()


@pytest.mark.asyncio
async def test_explicit_routing_requires_publication_inputs_and_environment(api) -> None:
    created = await api.post(
        "scenarios",
        json={
            "slug": "daily-report",
            "title": "Daily report",
            "summary": "Draft report flow",
            "aliases": ["日报"],
            "definition": _definition(),
        },
    )
    assert created.status_code == 201
    draft = await api.post("scenarios/resolve", json={"selector": "日报"})
    assert draft.json()["decision"] == "unavailable"

    published = await api.post(
        "scenarios/catalog/daily-report/versions/1/publish",
        json={"validation_evidence": "Validated report output against source data"},
    )
    assert published.status_code == 200
    missing = await api.post("scenarios/resolve", json={"selector": "日报"})
    assert missing.json()["decision"] == "incompatible"
    assert missing.json()["environment_mismatches"]["os"]["expected"] == "linux"

    missing_input = await api.post(
        "scenarios/resolve",
        json={
            "selector": "日报",
            "environment": {"os": "linux"},
        },
    )
    assert missing_input.json()["decision"] == "missing_inputs"
    assert missing_input.json()["missing_inputs"] == ["target"]

    ready = await api.post(
        "scenarios/resolve",
        json={
            "selector": "日报",
            "environment": {"os": "linux"},
            "parameters": {"target": "host-a"},
        },
    )
    assert ready.json()["decision"] == "ready_for_manual_checks"
    assert ready.json()["version"]["version"] == 1


@pytest.mark.asyncio
async def test_continuous_item_pins_version_and_deduplicates_runs(api) -> None:
    await _published_scenario(api)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await api.post(
        "scenarios/items",
        json={
            "scenario_slug": "host-check",
            "title": "Monitor host A",
            "goal": "Watch host A",
            "mode": "continuous",
            "parameters": {"target": "host-a"},
            "environment": {"os": "linux"},
            "next_check_at": past,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()["item"]
    item_id = item["id"]
    due = await api.get("scenarios/due")
    assert item_id in [entry["id"] for entry in due.json()["items"]]

    claimed = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={
            "idempotency_key": "check-1",
        },
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["claimed"] is True
    run_id = claimed.json()["run"]["id"]
    token = claimed.json()["lease_token"]
    duplicate = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={
            "idempotency_key": "check-1",
        },
    )
    assert duplicate.json()["claimed"] is False
    assert "lease_token" not in duplicate.json()
    overlap = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={
            "idempotency_key": "check-2",
            "force": True,
        },
    )
    assert overlap.status_code == 409

    next_check = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = {
        "lease_token": token,
        "outcome": "success",
        "observation": "alert",
        "summary": "Host is unreachable",
        "event_key": "host-a-down",
        "evidence": ["check://host-a/first"],
        "next_check_at": next_check,
        "state": {"completed_steps": ["connectivity"], "next": "retry connectivity"},
    }
    finished = await api.post(f"scenarios/items/{item_id}/runs/{run_id}/finish", json=result)
    assert finished.status_code == 200, finished.text
    assert finished.json()["run"]["signal"] == "alert"
    assert finished.json()["run"]["notification_recommended"] is True
    assert finished.json()["item"]["current_observation"] == "alert"
    again = await api.post(f"scenarios/items/{item_id}/runs/{run_id}/finish", json=result)
    assert again.status_code == 200
    runs = await api.get(f"scenarios/items/{item_id}/runs")
    assert len(runs.json()["items"]) == 1

    new_version = await api.post(
        "scenarios/catalog/host-check/versions",
        json={
            "definition": _definition("Check using updated method"),
        },
    )
    assert new_version.status_code == 201
    published = await api.post(
        "scenarios/catalog/host-check/versions/2/publish",
        json={
            "validation_evidence": "Updated method passed on disposable host",
        },
    )
    assert published.status_code == 200
    detail = await api.get(f"scenarios/items/{item_id}")
    assert detail.json()["version"]["version"] == 1
    revision = detail.json()["item"]["revision"]
    upgraded = await api.post(
        f"scenarios/items/{item_id}/upgrade",
        json={
            "expected_revision": revision,
            "version": 2,
            "reason": "Validated method update",
        },
    )
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["version"]["version"] == 2
    stale_upgrade = await api.post(
        f"scenarios/items/{item_id}/upgrade",
        json={
            "expected_revision": revision,
            "version": 1,
            "reason": "stale",
        },
    )
    assert stale_upgrade.status_code == 409


@pytest.mark.asyncio
async def test_standalone_item_runs_then_binds_to_published_scenario(api) -> None:
    missing_plan = await api.post(
        "scenarios/items",
        json={"title": "Monitor host", "goal": "Keep service stable", "mode": "continuous"},
    )
    assert missing_plan.status_code == 422
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await api.post(
        "scenarios/items",
        json={
            "title": "Monitor host",
            "goal": "Keep service stable",
            "working_plan": "Check the current state, record evidence, then choose the next check.",
            "mode": "continuous",
            "phase": "watching",
            "state": {"completed_steps": ["baseline"], "next": "first check"},
            "parameters": {"target": "host-a"},
            "environment": {"os": "linux"},
            "next_check_at": past,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()["item"]
    item_id = item["id"]
    assert item["scenario_id"] is None
    assert created.json()["version"] is None
    assert item["phase"] == "watching"
    assert item_id in [entry["id"] for entry in (await api.get("scenarios/due")).json()["items"]]

    claim = await api.post(
        f"scenarios/items/{item_id}/claim", json={"idempotency_key": "standalone-1"}
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["version"] is None
    assert claim.json()["run"]["version_id"] is None
    next_check = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    finish = await api.post(
        f"scenarios/items/{item_id}/runs/{claim.json()['run']['id']}/finish",
        json={
            "lease_token": claim.json()["lease_token"],
            "outcome": "success",
            "observation": "normal",
            "summary": "Initial check passed",
            "phase": "tracking",
            "state": {"completed_steps": ["baseline", "first check"], "next": "repeat"},
            "next_check_at": next_check,
        },
    )
    assert finish.status_code == 200, finish.text
    revision = finish.json()["item"]["revision"]

    await _published_scenario(api, "bound-check")
    mismatch = await api.post(
        f"scenarios/items/{item_id}/bind",
        json={
            "expected_revision": revision,
            "scenario_slug": "bound-check",
            "reason": "Validated",
            "environment": {"os": "windows"},
        },
    )
    assert mismatch.status_code == 422
    bound_response = await api.post(
        f"scenarios/items/{item_id}/bind",
        json={"expected_revision": revision, "scenario_slug": "bound-check", "reason": "Validated"},
    )
    assert bound_response.status_code == 200, bound_response.text
    bound = bound_response.json()
    assert bound["version"]["version"] == 1
    assert bound["item"]["working_plan"] == item["working_plan"]
    assert bound["item"]["state"] == finish.json()["item"]["state"]
    assert bound["item"]["phase"] == "tracking"
    assert bound["item"]["scenario_slug"] == "bound-check"
    assert bound["item"]["version_history"][-1]["reason"] == "Validated"
    assert (
        await api.post(
            f"scenarios/items/{item_id}/bind",
            json={
                "expected_revision": bound["item"]["revision"],
                "scenario_slug": "bound-check",
                "reason": "duplicate",
            },
        )
    ).status_code == 409
    second = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={"idempotency_key": "bound-2", "force": True},
    )
    assert second.status_code == 200, second.text
    assert second.json()["run"]["version_id"] == bound["version"]["id"]
    assert len((await api.get(f"scenarios/items/{item_id}/runs")).json()["items"]) == 2


@pytest.mark.asyncio
async def test_failed_check_becomes_unknown_and_pause_stops_claims(api) -> None:
    await _published_scenario(api, "service-check")
    created = await api.post(
        "scenarios/items",
        json={
            "scenario_slug": "service-check",
            "title": "Monitor service",
            "goal": "Watch service",
            "mode": "continuous",
            "parameters": {"target": "service-a"},
            "environment": {"os": "linux"},
        },
    )
    item_id = created.json()["item"]["id"]
    next_check = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    first = (
        await api.post(
            f"scenarios/items/{item_id}/claim",
            json={
                "idempotency_key": "first",
                "force": True,
            },
        )
    ).json()
    successful = await api.post(
        f"scenarios/items/{item_id}/runs/{first['run']['id']}/finish",
        json={
            "lease_token": first["lease_token"],
            "outcome": "success",
            "observation": "normal",
            "summary": "Service healthy",
            "next_check_at": next_check,
        },
    )
    assert successful.status_code == 200
    last_success = successful.json()["item"]["last_success_at"]

    second = (
        await api.post(
            f"scenarios/items/{item_id}/claim",
            json={
                "idempotency_key": "second",
                "force": True,
            },
        )
    ).json()
    failed = await api.post(
        f"scenarios/items/{item_id}/runs/{second['run']['id']}/finish",
        json={
            "lease_token": second["lease_token"],
            "outcome": "failure",
            "observation": "unknown",
            "summary": "Checker could not connect",
            "next_check_at": next_check,
        },
    )
    assert failed.status_code == 200
    assert failed.json()["item"]["current_observation"] == "unknown"
    assert failed.json()["item"]["last_success_at"] == last_success
    assert failed.json()["run"]["signal"] == "check_failed"

    revision = failed.json()["item"]["revision"]
    paused = await api.patch(
        f"scenarios/items/{item_id}",
        json={
            "expected_revision": revision,
            "status": "paused",
        },
    )
    assert paused.status_code == 200
    denied = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={
            "idempotency_key": "third",
            "force": True,
        },
    )
    assert denied.status_code == 409


@pytest.mark.asyncio
async def test_selectors_and_items_are_isolated_by_user(api, database) -> None:
    await _published_scenario(api, "private-check")
    duplicate = await api.post(
        "scenarios",
        json={
            "slug": "other-check",
            "title": "Duplicate alias",
            "summary": "Cannot reuse selector",
            "aliases": ["private-check"],
            "definition": _definition(),
        },
    )
    assert duplicate.status_code == 409
    item = await api.post(
        "scenarios/items",
        json={
            "scenario_slug": "private-check",
            "title": "Private item",
            "goal": "Check",
            "parameters": {"target": "host-a"},
            "environment": {"os": "linux"},
        },
    )
    item_id = item.json()["item"]["id"]

    other_id = uuid.uuid4()
    async with database() as session:
        session.add(User(id=other_id, github_id=2, username="other-user"))
        await session.commit()
    token, _ = create_access_token(user_id=other_id, username="other-user", role="user")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://integration/api/v1/",
        headers={"Authorization": f"Bearer {token}"},
    ) as other:
        assert (await other.get("scenarios/catalog/private-check")).status_code == 404
        assert (await other.get(f"scenarios/items/{item_id}")).status_code == 404
        assert (await other.get("scenarios")).json()["total"] == 0
        assert (await other.post("scenarios/resolve", json={"selector": "private-check"})).json()[
            "decision"
        ] == "not_found"


@pytest.mark.asyncio
async def test_expired_lease_rejects_stale_finish(api, monkeypatch) -> None:
    await _published_scenario(api, "lease-check")
    created = await api.post(
        "scenarios/items",
        json={
            "scenario_slug": "lease-check",
            "title": "Lease item",
            "goal": "Check once",
            "parameters": {"target": "host-a"},
            "environment": {"os": "linux"},
        },
    )
    item_id = created.json()["item"]["id"]
    first = (
        await api.post(
            f"scenarios/items/{item_id}/claim",
            json={
                "idempotency_key": "first",
            },
        )
    ).json()

    advanced = datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr("app.api.scenarios._now", lambda: advanced)
    second = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={
            "idempotency_key": "second",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["claimed"] is True
    old = await api.post(
        f"scenarios/items/{item_id}/runs/{first['run']['id']}/finish",
        json={
            "lease_token": first["lease_token"],
            "outcome": "success",
            "observation": "normal",
            "summary": "Old result",
        },
    )
    assert old.status_code == 409
    history = (await api.get(f"scenarios/items/{item_id}/runs")).json()["items"]
    assert next(run for run in history if run["id"] == first["run"]["id"])["status"] == "abandoned"


@pytest.mark.asyncio
async def test_secret_input_is_neither_stored_nor_echoed(api) -> None:
    definition = _definition()
    definition["input_fields"].append(
        {
            "name": "secret_ref",
            "description": "Runtime credential",
            "required": True,
            "secret": True,
        }
    )
    created = await api.post(
        "scenarios",
        json={
            "slug": "secret-check",
            "title": "Secret check",
            "summary": "Runtime credentials only",
            "definition": definition,
        },
    )
    assert created.status_code == 201
    assert (
        await api.post(
            "scenarios/catalog/secret-check/versions/1/publish",
            json={
                "validation_evidence": "Checked without persisting runtime credential values",
            },
        )
    ).status_code == 200
    resolved = await api.post(
        "scenarios/resolve",
        json={
            "selector": "secret-check",
            "parameters": {
                "target": "host-a",
                "secret_ref": "privatevalue",
            },
            "environment": {"os": "linux"},
        },
    )
    assert resolved.json()["decision"] == "incompatible"
    assert resolved.json()["invalid_inputs"] == ["secret_ref"]
    assert "privatevalue" not in resolved.text
    item = await api.post(
        "scenarios/items",
        json={
            "scenario_slug": "secret-check",
            "title": "Unsafe",
            "goal": "Check",
            "parameters": {"target": "host-a", "secret_ref": "privatevalue"},
            "environment": {"os": "linux"},
        },
    )
    assert item.status_code == 422
    assert "privatevalue" not in item.text
