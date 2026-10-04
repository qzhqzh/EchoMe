"""A recorded household-network case exercises continuing work without live access.

The values below are historical, non-secret observations. This test never probes
or changes a real network, and must not mark the current network as healthy.
"""

from datetime import datetime, timedelta, timezone

import pytest


def _read_only_definition() -> dict:
    return {
        "applicability": "Only for the named home network after confirming the current host and path.",
        "exclusions": "No router changes, proxy toggles, firmware updates, or full-speed test without a separate decision.",
        "input_fields": [{"name": "site", "description": "Confirmed site alias", "required": True}],
        "required_environment": {"platform": "windows", "access": "home"},
        "steps": [
            "Read the dated network record and mark older measurements as historical.",
            "Refresh the current interface, gateway, DNS, proxy, and VPN state when the host is available.",
            "Run a bounded gateway and public-path check and save raw samples with timestamps.",
        ],
        "verification": [
            "Distinguish a successful measurement, an observed alert, and an unavailable checker.",
            "Keep every acceptance metric pending until its stated method and sample window are met.",
        ],
        "recovery": [
            "If the host or checker is unavailable, report unknown and keep the last dated result."
        ],
        "execution_ref": None,
        "source_refs": ["case-study:2026-10-04-home-network-v0.3"],
    }


@pytest.mark.asyncio
async def test_home_network_case_preserves_historical_evidence_and_pending_work(api) -> None:
    draft = await api.post(
        "scenarios",
        json={
            "slug": "home-network-readonly",
            "title": "Household network read-only diagnosis",
            "summary": "Repeatable measurements and evidence review for the known home network",
            "aliases": ["家庭网络只读排查"],
            "definition": _read_only_definition(),
        },
    )
    assert draft.status_code == 201, draft.text
    unavailable = await api.post("scenarios/resolve", json={"selector": "家庭网络只读排查"})
    assert unavailable.json()["decision"] == "unavailable"

    historical_state = {
        "source": "case-study:2026-10-04-home-network-v0.3",
        "source_timezone": "Asia/Shanghai",
        "historical": {
            "wifi_download_mbps": [193.53, 250.65, 224.81, 288.58],
            "wifi_upload_mbps": [51.70, 53.15, 52.64, 52.89],
            "gateway_idle_samples": 600,
            "gateway_idle_successes": 600,
            "gateway_idle_p95_ms": 3,
            "gateway_download_p95_ms": 63,
        },
        "acceptance": {
            "Q01": "investigating",
            "Q02": "investigating",
            "Q03": "unverified",
            "Q04": "passed_for_one_dated_low_load_window",
            "Q05": "investigating",
            "Q06": "investigating",
            "Q07": "unverified",
            "Q08": "needs_on_site_support",
        },
        "next_action": "Compare the same host on a confirmed gigabit wired path, then repeat bounded load checks.",
        "dependency": "On-site cable connection has not been confirmed.",
        "root_cause": "unknown",
        "network_changes_authorized": False,
    }
    created = await api.post(
        "scenarios/items",
        json={
            "title": "Home network performance diagnosis",
            "goal": "Find the cause of inconsistent Wi-Fi download and elevated loaded latency.",
            "working_plan": (
                "Preserve the dated baseline; confirm host and path; perform a wired comparison "
                "when available; isolate one cause at a time. Discuss configuration changes "
                "with the user before applying them."
            ),
            "mode": "continuous",
            "phase": "awaiting_wired_comparison",
            "state": historical_state,
            "parameters": {"site": "home"},
            "environment": {"platform": "windows", "access": "home"},
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()["item"]
    item_id = item["id"]
    assert created.json()["version"] is None
    assert item["current_observation"] == "unknown"
    assert item["state"]["acceptance"]["Q04"] == "passed_for_one_dated_low_load_window"
    assert item["state"]["root_cause"] == "unknown"
    discovered = await api.get("scenarios/items", params={"query": "network performance"})
    assert [entry["id"] for entry in discovered.json()["items"]] == [item_id]
    assert (await api.get("scenarios/items", params={"query": "no such matter"})).json()[
        "total"
    ] == 0

    resumed = await api.get(f"scenarios/items/{item_id}")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["item"]["state"] == historical_state
    assert resumed.json()["version"] is None

    # The current executor cannot reach the Windows host. Record that attempt
    # without turning old measurements into a current success or alert.
    claimed = await api.post(
        f"scenarios/items/{item_id}/claim",
        json={"idempotency_key": "case-review-no-host", "force": True},
    )
    assert claimed.status_code == 200, claimed.text
    next_check = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    finished = await api.post(
        f"scenarios/items/{item_id}/runs/{claimed.json()['run']['id']}/finish",
        json={
            "lease_token": claimed.json()["lease_token"],
            "outcome": "skipped",
            "observation": "unknown",
            "summary": "Historical record reviewed; the Windows host was not accessible for a fresh check.",
            "evidence": ["case-study:2026-10-04-home-network-v0.3"],
            "next_check_at": next_check,
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["item"]["current_observation"] == "unknown"
    assert finished.json()["item"]["last_success_at"] is None
    assert finished.json()["item"]["state"] == historical_state
    assert finished.json()["run"]["notification_recommended"] is False

    published = await api.post(
        "scenarios/catalog/home-network-readonly/versions/1/publish",
        json={
            "validation_evidence": (
                "2026-10-04 dated case: device state was read, a 600-sample low-load "
                "gateway check was saved, and load samples were distinguished from "
                "formal acceptance. Validates the read-only diagnostic steps only."
            )
        },
    )
    assert published.status_code == 200, published.text
    incompatible = await api.post(
        "scenarios/resolve",
        json={
            "selector": "家庭网络只读排查",
            "parameters": {"site": "home"},
            "environment": {"platform": "linux", "access": "workspace"},
        },
    )
    assert incompatible.json()["decision"] == "incompatible"

    bound = await api.post(
        f"scenarios/items/{item_id}/bind",
        json={
            "expected_revision": finished.json()["item"]["revision"],
            "scenario_slug": "home-network-readonly",
            "reason": "Validated only the read-only diagnostic portion of the dated case",
        },
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["item"]["working_plan"] == item["working_plan"]
    assert bound.json()["item"]["state"] == historical_state
    assert bound.json()["item"]["current_observation"] == "unknown"
    assert len((await api.get(f"scenarios/items/{item_id}/runs")).json()["items"]) == 1
    by_scenario = await api.get(
        "scenarios/items", params={"scenario_slug": "home-network-readonly"}
    )
    assert [entry["id"] for entry in by_scenario.json()["items"]] == [item_id]

    new_definition = _read_only_definition()
    new_definition["steps"].append("Compare with a verified gigabit wired connection.")
    new_version = await api.post(
        "scenarios/catalog/home-network-readonly/versions",
        json={"definition": new_definition},
    )
    assert new_version.status_code == 201, new_version.text
    denied = await api.post(
        f"scenarios/items/{item_id}/upgrade",
        json={
            "expected_revision": bound.json()["item"]["revision"],
            "version": 2,
            "reason": "Wired comparison is still pending",
        },
    )
    assert denied.status_code == 409
    assert (await api.get(f"scenarios/items/{item_id}")).json()["version"]["version"] == 1
