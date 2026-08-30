"""The checked-in current-state documentation is part of the release contract."""

from scripts.check_project_truth import check_project_truth


def test_authoritative_project_truth_is_synchronized() -> None:
    assert check_project_truth() == []
