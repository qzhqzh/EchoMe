"""Resumable, idempotent ArtifactChunk backfill through the Hub API."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import yaml

CONFIG_FILE = Path.home() / ".echome" / "config.yaml"


def _config() -> dict[str, str]:
    payload = (
        yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        if CONFIG_FILE.exists()
        else {}
    )
    return {
        "hub_url": str(payload.get("hub_url", "http://127.0.0.1:20000")).rstrip("/"),
        "token": str(payload.get("token", "")),
    }


def _load_checkpoint(path: Path, base_url: str, project_id: str) -> dict[str, Any]:
    initial = {
        "after_path": None,
        "complete": False,
        "totals": {"batches": 0, "artifacts": 0, "chunks": 0, "embedded": 0},
    }
    if not path.exists():
        return initial
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("base_url") != base_url or payload.get("project_id") != project_id:
        raise ValueError("Checkpoint belongs to another Hub or project")
    totals = payload.get("totals") or {}
    return {
        "after_path": payload.get("after_path"),
        "complete": bool(payload.get("complete", False)),
        "totals": {
            key: int(totals.get(key, 0))
            for key in ("batches", "artifacts", "chunks", "embedded")
        },
    }


async def run_backfill(
    *,
    base_url: str,
    token: str,
    project_id: str,
    batch_size: int,
    checkpoint: Path,
    include_embeddings: bool,
) -> dict[str, Any]:
    checkpoint_state = _load_checkpoint(checkpoint, base_url, project_id)
    cursor = checkpoint_state["after_path"]
    totals = checkpoint_state["totals"]
    if checkpoint_state["complete"]:
        return {**totals, "complete": True, "checkpoint": str(checkpoint)}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=180) as client:
        while True:
            response = await client.post(
                "/api/v1/project-knowledge/artifacts/chunks/rebuild",
                json={
                    "project_id": project_id,
                    "limit": batch_size,
                    "after_path": cursor,
                    "missing_only": True,
                    "include_embeddings": include_embeddings,
                },
            )
            response.raise_for_status()
            batch = response.json()
            totals["batches"] += 1
            totals["artifacts"] += int(batch["artifact_count"])
            totals["chunks"] += int(batch["chunk_count"])
            totals["embedded"] += int(batch["embedded_count"])
            cursor = batch.get("next_cursor")
            checkpoint.write_text(
                json.dumps(
                    {
                        "base_url": base_url,
                        "project_id": project_id,
                        "after_path": cursor,
                        "complete": not batch.get("has_more", False),
                        "totals": totals,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if not batch.get("has_more", False):
                return {**totals, "complete": True, "checkpoint": str(checkpoint)}


async def repair_missing_embeddings(
    *,
    base_url: str,
    token: str,
    project_id: str,
    batch_size: int,
) -> dict[str, Any]:
    """Rebuild artifacts whose existing chunks are missing embeddings."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    page_size = 2000
    missing_artifact_ids: set[str] = set()
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=180) as client:
        offset = 0
        while True:
            response = await client.get(
                "/api/v1/project-knowledge/artifacts/chunks",
                params={
                    "project_id": project_id,
                    "include_content": "false",
                    "offset": offset,
                    "limit": page_size,
                },
            )
            response.raise_for_status()
            items = response.json()["items"]
            missing_artifact_ids.update(
                item["artifact_id"] for item in items if not item["has_embedding"]
            )
            if len(items) < page_size:
                break
            offset += len(items)

        ordered_ids = sorted(missing_artifact_ids)
        rebuilt_artifacts = 0
        rebuilt_chunks = 0
        for index in range(0, len(ordered_ids), batch_size):
            artifact_ids = ordered_ids[index : index + batch_size]
            response = await client.post(
                "/api/v1/project-knowledge/artifacts/chunks/rebuild",
                json={
                    "project_id": project_id,
                    "artifact_ids": artifact_ids,
                    "limit": len(artifact_ids),
                    "missing_only": False,
                    "include_embeddings": True,
                },
            )
            response.raise_for_status()
            batch = response.json()
            rebuilt_artifacts += int(batch["artifact_count"])
            rebuilt_chunks += int(batch["embedded_count"])

    return {
        "artifacts_with_missing_embeddings": len(ordered_ids),
        "rebuilt_artifacts": rebuilt_artifacts,
        "rebuilt_embeddings": rebuilt_chunks,
        "complete": True,
    }


def main() -> None:
    config = _config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=config["hub_url"])
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--include-embeddings", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-configured-hub", action="store_true")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    if not args.apply:
        raise SystemExit("Backfill is write-capable; pass --apply after reviewing the target")
    if base_url == config["hub_url"] and not args.allow_configured_hub:
        raise SystemExit("Refusing configured Hub without --allow-configured-hub")
    result = asyncio.run(
        run_backfill(
            base_url=base_url,
            token=config["token"],
            project_id=args.project_id,
            batch_size=args.batch_size,
            checkpoint=args.checkpoint,
            include_embeddings=args.include_embeddings,
        )
    )
    if args.include_embeddings:
        result["embedding_repair"] = asyncio.run(
            repair_missing_embeddings(
                base_url=base_url,
                token=config["token"],
                project_id=args.project_id,
                batch_size=args.batch_size,
            )
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
