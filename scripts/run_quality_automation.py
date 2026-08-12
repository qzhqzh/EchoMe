"""Invoke proposal-only Project Knowledge automation through the Hub API."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

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


async def run(args: argparse.Namespace) -> dict:
    config = _config()
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), headers=headers, timeout=90
    ) as client:
        response = await client.post(
            "/api/v1/project-knowledge/automation/proposals/run",
            json={
                "project_id": args.project_id,
                "dry_run": not args.generate,
                "required_snapshots": args.required_snapshots,
                "include_sleep": not args.no_sleep,
                "include_revalidation": not args.no_revalidation,
                "idempotency_key": args.idempotency_key,
            },
        )
        response.raise_for_status()
        return response.json()


def main() -> None:
    config = _config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=config["hub_url"])
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--required-snapshots", type=int, default=3)
    parser.add_argument("--no-sleep", action="store_true")
    parser.add_argument("--no-revalidation", action="store_true")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
