"""Tests for deterministic retrieval replay comparisons."""

from app.services.retrieval_replay import build_replay_report, compare_retrieval_replay


def test_replay_detects_expected_memory_rank_regression() -> None:
    item = compare_retrieval_replay(
        log_id="log-1",
        query="Git workflow",
        expected_ids=["expected"],
        previous_expected_rank=1,
        previous_results=[{"id": "expected"}, {"id": "other"}],
        current_results=[{"id": "other"}, {"id": "expected"}],
        current_trace={"strategy": "hybrid_memory"},
    )

    assert item["outcome"] == "regressed"
    assert item["current_expected_rank"] == 2
    assert item["top_k_jaccard"] == 1.0


def test_replay_report_requires_scored_logs_and_zero_regressions() -> None:
    improved = compare_retrieval_replay(
        log_id="log-1",
        query="network",
        expected_ids=["expected"],
        previous_expected_rank=None,
        previous_results=[{"id": "other"}],
        current_results=[{"id": "expected"}],
        current_trace={},
    )
    unscored = compare_retrieval_replay(
        log_id="log-2",
        query="unscored",
        expected_ids=[],
        previous_expected_rank=None,
        previous_results=[],
        current_results=[],
        current_trace={},
    )

    report = build_replay_report([improved, unscored])

    assert report["scored_count"] == 1
    assert report["improved"] == 1
    assert report["passed"] is True


def test_replay_marks_a_different_recorded_strategy_unscored() -> None:
    item = compare_retrieval_replay(
        log_id="log-summary",
        query="Git workflow",
        expected_ids=["expected"],
        previous_expected_rank=1,
        previous_results=[{"id": "expected"}],
        current_results=[],
        current_trace={"replay_skipped": True},
        comparable=False,
    )

    assert item["outcome"] == "unscored"
    assert item["expected_ids"] == ["expected"]
