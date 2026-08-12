"""End-to-end HTTP and MCP smoke checks for Project Knowledge."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from echome_mcp import hub_client, server

CONFIG_FILE = Path.home() / ".echome" / "config.yaml"


def _config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        return {"hub_url": "http://127.0.0.1:20000", "token": ""}
    payload = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    return {
        "hub_url": str(payload.get("hub_url", "http://127.0.0.1:20000")).rstrip("/"),
        "token": str(payload.get("token", "")),
    }


async def _json_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected object from {path}")
    return payload


async def run_smoke(
    base_url: str,
    project_id: str,
    *,
    exercise_writes: bool = False,
) -> dict[str, Any]:
    config = _config()
    base_url = base_url.rstrip("/")
    if exercise_writes and base_url == config["hub_url"]:
        raise ValueError("Write smoke refuses to target the configured Hub URL")
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
    }
    checks: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60) as client:
        health = await _json_request(client, "GET", "/health")
        assert health.get("status") == "ok"
        checks["health"] = True

        search = await _json_request(
            client,
            "POST",
            "/api/v1/memories/search",
            json={"query": "EchoMe project context", "project_id": project_id, "top_k": 5},
        )
        assert isinstance(search.get("results"), list)
        checks["memory_search"] = len(search["results"])

        sleep = await _json_request(
            client,
            "GET",
            "/api/v1/observability/sleep-sessions",
            params={"limit": 1},
        )
        assert "items" in sleep
        checks["sleep_observability"] = True

        context_request = {
            "project_id": project_id,
            "task": "Verify Project Knowledge HTTP and MCP compatibility",
            "changed_paths": ["hub/app/api/project_knowledge.py", "echome_mcp/server.py"],
            "mode": "impact",
            "limit": 10,
            "token_budget": 4000,
            "record_run": False,
        }
        context = await _json_request(
            client,
            "POST",
            "/api/v1/project-knowledge/context",
            json=context_request,
        )
        assert context.get("project", {}).get("id") == project_id
        assert context.get("token_used", 0) <= context.get("token_budget", 0)
        assert isinstance(context.get("retrieval_trace"), dict)
        checks["project_context"] = {
            "constraints": len(context.get("constraints", [])),
            "evidence": len(context.get("evidence", [])),
            "token_used": context.get("token_used"),
        }

        impact = await _json_request(
            client,
            "POST",
            "/api/v1/project-knowledge/impact",
            json={
                "project_id": project_id,
                "task": "Add structured MCP output while preserving API compatibility",
                "changed_paths": ["echome_mcp/server.py"],
                "depth": 1,
                "limit": 10,
            },
        )
        assert impact.get("project_id") == project_id
        checks["project_impact"] = len(impact.get("constraints", []))

        eval_cases = await _json_request(
            client,
            "GET",
            "/api/v1/project-knowledge/eval/cases",
        )
        assert len(eval_cases.get("cases", [])) >= 20
        checks["quality_cases"] = len(eval_cases["cases"])

        if exercise_writes:
            evidence_artifact_id = next(
                (
                    item.get("artifact_id")
                    for item in context.get("evidence", [])
                    if item.get("artifact_id")
                ),
                None,
            )
            artifacts = await _json_request(
                client,
                "GET",
                "/api/v1/project-knowledge/artifacts",
                params={"project_id": project_id, "include_content": True, "limit": 1000},
            )
            artifact = next(
                (item for item in artifacts["items"] if item["id"] == evidence_artifact_id),
                artifacts["items"][0],
            )
            artifact_id = artifact["id"]
            rebuilt = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/artifacts/chunks/rebuild",
                json={
                    "project_id": project_id,
                    "artifact_ids": [artifact_id],
                    "include_embeddings": False,
                },
            )
            assert rebuilt["artifact_count"] == 1
            assert rebuilt["chunk_count"] > 0
            checks["chunk_rebuild"] = rebuilt["chunk_count"]

            view = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/views",
                json={
                    "project_id": project_id,
                    "kind": "summary",
                    "query": "isolated smoke freshness view",
                    "content": "A temporary derived view used only in the migration test database.",
                    "source_watermark": {"artifact_ids": [artifact_id]},
                    "refresh_mode": "derived",
                    "producer": "smoke_test",
                },
            )
            marker = f"\n\n<!-- echome-isolated-smoke-revision:{view['id']} -->"
            if marker not in artifact["content"]:
                revised_content = artifact["content"] + marker
                revised_hash = hashlib.sha256(revised_content.encode("utf-8")).hexdigest()
                applied = await _json_request(
                    client,
                    "POST",
                    "/api/v1/project-knowledge/artifacts/sync/apply",
                    json={
                        "project_id": project_id,
                        "artifacts": [
                            {
                                "logical_path": artifact["logical_path"],
                                "content_hash": revised_hash,
                                "size_bytes": len(revised_content.encode("utf-8")),
                                "kind": artifact["kind"],
                                "title": artifact["title"],
                                "source_uri": artifact.get("source_uri"),
                                "metadata": {"source": "isolated_smoke"},
                                "content": revised_content,
                            }
                        ],
                    },
                )
                assert len(applied["created"]) == 1
            views = await _json_request(
                client,
                "GET",
                "/api/v1/project-knowledge/views",
                params={"project_id": project_id, "limit": 500},
            )
            current_view = next(item for item in views["items"] if item["id"] == view["id"])
            assert current_view["status"] == "stale"
            checks["derived_view_staleness"] = True

            proposals = await _json_request(
                client,
                "GET",
                "/api/v1/project-knowledge/revalidation-proposals",
                params={"project_id": project_id, "status": "pending", "limit": 500},
            )
            assert any(
                item.get("source_refs") and item["source_refs"][0].get("current_artifact_id")
                for item in proposals["items"]
            )
            checks["automatic_revalidation_proposal"] = True

            constraints = await _json_request(
                client,
                "GET",
                "/api/v1/project-knowledge/constraints",
                params={"project_id": project_id, "status": "active", "limit": 10},
            )
            embedded_constraints = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/constraints/embeddings/rebuild",
                json={"project_id": project_id, "limit": 200},
            )
            assert embedded_constraints["embedded_count"] > 0
            first_constraint, second_constraint = constraints["items"][:2]
            conflict_edge = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/edges",
                json={
                    "project_id": project_id,
                    "source_constraint_id": first_constraint["id"],
                    "target_constraint_id": second_constraint["id"],
                    "relation": "conflicts_with",
                    "reason": "Controlled quality-evaluation fixture in the isolated database.",
                    "created_by": "bootstrap",
                    "source_metadata": {"fixture": "context_quality_eval"},
                },
            )
            assert conflict_edge["relation"] == "conflicts_with"
            checks["constraint_embedding_rebuild"] = embedded_constraints["embedded_count"]
            checks["conflict_fixture"] = True
            constraint = first_constraint
            proposal_body = {
                "project_id": project_id,
                "constraint_id": constraint["id"],
                "base_version": constraint["version"],
                "reason": "Verify optimistic revalidation in the isolated smoke database.",
                "proposal": {"action": "revise"},
                "source_refs": [{"artifact_id": artifact_id}],
                "idempotency_key": (
                    f"smoke-revalidate-{constraint['id']}-v{constraint['version']}"
                ),
                "created_by": "ai",
            }
            first_proposal = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/revalidation-proposals",
                json=proposal_body,
            )
            second_proposal = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/revalidation-proposals",
                json=proposal_body,
            )
            assert first_proposal["id"] == second_proposal["id"]
            revalidated = await _json_request(
                client,
                "POST",
                f"/api/v1/project-knowledge/revalidation-proposals/{first_proposal['id']}/apply",
                json={
                    "expected_base_version": constraint["version"],
                    "changes": {
                        "expected_version": constraint["version"],
                        "rationale": "Validated by isolated Project Knowledge smoke.",
                    },
                },
            )
            assert revalidated["constraint"]["version"] == constraint["version"] + 1
            duplicate_apply = await client.post(
                f"/api/v1/project-knowledge/revalidation-proposals/{first_proposal['id']}/apply",
                json={
                    "expected_base_version": constraint["version"],
                    "changes": {"expected_version": constraint["version"]},
                },
            )
            assert duplicate_apply.status_code == 409
            stale_proposal = await client.post(
                "/api/v1/project-knowledge/revalidation-proposals",
                json={
                    **proposal_body,
                    "idempotency_key": proposal_body["idempotency_key"] + "-stale",
                },
            )
            assert stale_proposal.status_code == 409
            checks["revalidation_version_guard"] = True

            artifact_by_path = {item["logical_path"]: item for item in artifacts["items"]}
            event_fixtures = [
                (
                    "failure",
                    "Migration rollback rehearsal caught an invalid schema transition",
                    "Database migration for hub/alembic/versions/011_context_compiler_and_project_events.py failed before rollback verification.",
                    "hub/alembic/versions/011_context_compiler_and_project_events.py",
                    "quality-migration-failure-v1",
                ),
                (
                    "test_result",
                    "Migration upgrade and rollback rehearsal passed on a database copy",
                    "Verified backup, upgrade, rollback, UUID preservation, and re-upgrade for hub/alembic/versions/011_context_compiler_and_project_events.py.",
                    "hub/alembic/versions/011_context_compiler_and_project_events.py",
                    "quality-migration-test-v1",
                ),
                (
                    "failure",
                    "Web build failed because the locked Cytoscape dependency was absent",
                    "npm run build failed for web/package.json until the locked dependency tree was restored.",
                    "web/package.json",
                    "quality-web-failure-v1",
                ),
                (
                    "fix",
                    "Clean dependency installation restored the Web build",
                    "A clean install for web/package.json restored Cytoscape and its type declarations.",
                    "web/package.json",
                    "quality-web-fix-v1",
                ),
                (
                    "test_result",
                    "Production Web build passed after dependency restoration",
                    "npm run build passed for web/package.json after the dependency fix.",
                    "web/package.json",
                    "quality-web-test-v1",
                ),
                (
                    "failure",
                    "Temporary smoke failure event",
                    "Project Knowledge smoke should recall this failure before changing server.py.",
                    artifact["logical_path"],
                    "project-knowledge-smoke-failure-v1",
                ),
            ]
            created_events = []
            for event_type, title, content, logical_path, idempotency_key in event_fixtures:
                linked_artifact = artifact_by_path.get(logical_path, artifact)
                event_body = {
                    "project_id": project_id,
                    "event_type": event_type,
                    "title": title,
                    "content": content,
                    "source": "smoke_test",
                    "idempotency_key": idempotency_key,
                    "links": [
                        {
                            "target_type": "artifact",
                            "target_id": linked_artifact["id"],
                            "relation": "observed_in",
                        }
                    ],
                }
                created_events.append(
                    await _json_request(
                        client, "POST", "/api/v1/project-knowledge/events", json=event_body
                    )
                )
            first_event = created_events[-1]
            second_event = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/events",
                json={
                    "project_id": project_id,
                    "event_type": "failure",
                    "title": "Temporary smoke failure event",
                    "content": "Project Knowledge smoke should recall this failure before changing server.py.",
                    "source": "smoke_test",
                    "idempotency_key": "project-knowledge-smoke-failure-v1",
                    "links": [
                        {
                            "target_type": "artifact",
                            "target_id": artifact_id,
                            "relation": "observed_in",
                        }
                    ],
                },
            )
            assert first_event["id"] == second_event["id"]
            preflight = await _json_request(
                client,
                "POST",
                "/api/v1/project-knowledge/preflight",
                json={
                    "project_id": project_id,
                    "task": "Change server.py Project Knowledge context",
                    "changed_paths": ["server.py"],
                    "planned_actions": ["run smoke"],
                },
            )
            assert preflight.get("read_only") is True
            assert all(item.get("evidence") for item in preflight.get("warnings", []))
            checks["event_idempotency"] = True
            checks["preflight_warnings"] = len(preflight.get("warnings", []))

    original_loader = hub_client._load_config
    hub_client._load_config = lambda: {"hub_url": base_url, "token": config["token"]}
    try:
        mcp_result = await server.call_tool(
            "echome_project_context",
            {
                "project_id": project_id,
                "task": "Verify structured MCP project context",
                "changed_paths": ["echome_mcp/server.py"],
                "token_budget": 3000,
                "record_run": False,
            },
        )
    finally:
        hub_client._load_config = original_loader
    assert mcp_result.isError is False
    assert isinstance(mcp_result.structuredContent, dict)
    assert json.loads(mcp_result.content[0].text) == mcp_result.structuredContent
    checks["mcp_structured_content"] = True
    return {"ok": True, "base_url": base_url, "project_id": project_id, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:20000")
    parser.add_argument("--project-id", default="qzhqzh/EchoMe")
    parser.add_argument("--exercise-writes", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        run_smoke(
            args.base_url,
            args.project_id,
            exercise_writes=args.exercise_writes,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
