"""Local identity follows bounded Git metadata, never repository code or includes."""

import os
from pathlib import Path

import pytest

from echome.core.hook_project import MAX_CONFIG_BYTES, MAX_PARENT_LEVELS, local_project_hints


def write_config(directory: Path, remote: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config").write_text('[remote "origin"]\n    url = ' + remote + "\n")


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/qzhqzh/biomed.git", "https://github.com/qzhqzh/biomed.git"),
        ("git@github.com:qzhqzh/biomed.git", "ssh://github.com/qzhqzh/biomed.git"),
        (
            "ssh://git@git.example.test:2222/team/repo.git",
            "ssh://git.example.test:2222/team/repo.git",
        ),
        (
            "https://SYNTHETIC_USER:SYNTHETIC_PASSWORD@git.example.test/team/repo.git?token=SYNTHETIC_QUERY#SYNTHETIC_FRAGMENT",
            "https://git.example.test/team/repo.git",
        ),
        ('"https://git.example.test/team/repo.git"', "https://git.example.test/team/repo.git"),
    ],
)
def test_nested_working_directory_reads_nearest_origin_safely(
    tmp_path: Path, remote: str, expected: str
) -> None:
    write_config(tmp_path / ".git", remote)
    cwd = tmp_path / "web" / "src"
    cwd.mkdir(parents=True)
    assert local_project_hints(str(cwd)) == [expected]


def test_linked_worktree_uses_relative_gitdir_and_commondir(tmp_path: Path) -> None:
    common = tmp_path / "main" / ".git"
    write_config(common, "git@github.com:qzhqzh/EchoMe.git")
    gitdir = common / "worktrees" / "feature"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n")
    cwd = tmp_path / "feature"
    cwd.mkdir()
    (cwd / ".git").write_text("gitdir: ../main/.git/worktrees/feature\n")
    assert local_project_hints(str(cwd)) == ["ssh://github.com/qzhqzh/EchoMe.git"]


def test_gitdir_file_without_commondir_supports_absolute_metadata_path(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    write_config(metadata, "https://git.example.test/team/repo.git")
    cwd = tmp_path / "checkout"
    cwd.mkdir()
    (cwd / ".git").write_text("gitdir: " + str(metadata) + "\n")
    assert local_project_hints(str(cwd)) == ["https://git.example.test/team/repo.git"]


def test_nearest_repository_boundary_prevents_wrong_parent_fallback(tmp_path: Path) -> None:
    write_config(tmp_path / ".git", "https://git.example.test/parent/repo.git")
    cwd = tmp_path / "nested"
    cwd.mkdir()
    (cwd / ".git").mkdir()
    (cwd / ".git" / "config").write_text("[core]\n    bare = false\n")
    assert local_project_hints(str(cwd)) == []


def test_parent_traversal_is_bounded(tmp_path: Path) -> None:
    write_config(tmp_path / ".git", "https://git.example.test/team/repo.git")
    cwd = tmp_path.joinpath(*["nested"] * MAX_PARENT_LEVELS)
    cwd.mkdir(parents=True)
    assert local_project_hints(str(cwd)) == []
    assert local_project_hints(str(cwd.parent)) == ["https://git.example.test/team/repo.git"]


@pytest.mark.parametrize(
    "remote",
    [
        "file:///private/repo.git",
        "/private/repo.git",
        "ext::sh -c 'echo malicious'",
        "ext::sh",
        "https://host.example.test/team/ghp_SYNTHETICSECRET123456.git",
        "https://host.example.test/team/repo%0Apassword=synthetic",
        "https://host.example.test:invalid/team/repo.git",
        "SYNTHETIC_USER:SYNTHETIC_PASSWORD@host.example.test:team/repo.git",
    ],
)
def test_unsupported_or_credential_bearing_remote_is_rejected(tmp_path: Path, remote: str) -> None:
    write_config(tmp_path / ".git", remote)
    assert local_project_hints(str(tmp_path)) == []


def test_config_includes_and_default_values_are_not_followed(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    extra = tmp_path / "included-config"
    extra.write_text('[remote "origin"]\n url = https://private.example.test/private/repo.git\n')
    (git / "config").write_text(
        "[include]\n path = "
        + str(extra)
        + '\n[DEFAULT]\n url = https://wrong.example/repo\n[remote "origin"]\n'
    )
    assert local_project_hints(str(tmp_path)) == []


@pytest.mark.parametrize(
    "kind", ["config_symlink", "marker_symlink", "fifo", "oversized", "bad_pointer"]
)
def test_unsafe_metadata_returns_no_hint(tmp_path: Path, kind: str) -> None:
    marker = tmp_path / ".git"
    if kind == "marker_symlink":
        target = tmp_path / "other"
        write_config(target, "https://git.example.test/team/repo.git")
        marker.symlink_to(target)
    elif kind == "bad_pointer":
        marker.write_text("gitdir: missing\nsecond unexpected line\n")
    else:
        marker.mkdir()
        config = marker / "config"
        if kind == "config_symlink":
            target = tmp_path / "secret-file"
            target.write_text(
                '[remote "origin"]\n url=https://private.example.test/private/repo.git'
            )
            config.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(config)
        else:
            config.write_text("x" * (MAX_CONFIG_BYTES + 1))
    assert local_project_hints(str(tmp_path)) == []


def test_commondir_is_not_followed_recursively(tmp_path: Path) -> None:
    gitdir = tmp_path / "metadata"
    gitdir.mkdir()
    other = tmp_path / "other-metadata"
    other.mkdir()
    (gitdir / "commondir").write_text("../other-metadata\n")
    (other / "commondir").write_text("../metadata\n")
    cwd = tmp_path / "checkout"
    cwd.mkdir()
    (cwd / ".git").write_text("gitdir: ../metadata\n")
    assert local_project_hints(str(cwd)) == []


def test_no_git_metadata_does_not_guess_from_directory_name(tmp_path: Path) -> None:
    cwd = tmp_path / "biomed"
    cwd.mkdir()
    assert local_project_hints(str(cwd)) == []
    assert local_project_hints("relative/path") == []
