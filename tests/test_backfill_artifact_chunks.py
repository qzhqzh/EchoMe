"""Tests for the resumable ArtifactChunk backfill checkpoint."""

import json

from scripts.backfill_artifact_chunks import _load_checkpoint


def test_load_checkpoint_preserves_accumulated_totals(tmp_path):
    checkpoint = tmp_path / "chunks.checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:20000",
                "project_id": "qzhqzh/EchoMe",
                "after_path": "SECURITY.md",
                "complete": False,
                "totals": {
                    "batches": 5,
                    "artifacts": 125,
                    "chunks": 442,
                    "embedded": 416,
                },
            }
        ),
        encoding="utf-8",
    )

    state = _load_checkpoint(
        checkpoint,
        "http://127.0.0.1:20000",
        "qzhqzh/EchoMe",
    )

    assert state == {
        "after_path": "SECURITY.md",
        "complete": False,
        "totals": {
            "batches": 5,
            "artifacts": 125,
            "chunks": 442,
            "embedded": 416,
        },
    }
