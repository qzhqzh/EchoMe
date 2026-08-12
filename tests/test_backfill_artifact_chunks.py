"""Tests for the resumable ArtifactChunk backfill checkpoint."""

import json

from scripts.backfill_artifact_chunks import _load_checkpoint, _write_checkpoint


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


def test_write_checkpoint_atomically_replaces_previous_state(tmp_path):
    checkpoint = tmp_path / "nested" / "chunks.checkpoint.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text('{"old": true}\n', encoding="utf-8")
    payload = {"after_path": "README.md", "complete": False, "totals": {"batches": 1}}

    _write_checkpoint(checkpoint, payload)

    assert json.loads(checkpoint.read_text(encoding="utf-8")) == payload
    assert not checkpoint.with_name(f".{checkpoint.name}.tmp").exists()
