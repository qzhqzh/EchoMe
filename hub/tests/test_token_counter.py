"""Tests for offline-safe token counter initialization."""

from pathlib import Path

from app.services import token_counter


def test_encoding_loader_skips_network_when_cache_is_missing(monkeypatch, tmp_path: Path) -> None:
    called = False

    def fake_get_encoding(name: str) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(token_counter, "_encoding_cache_path", lambda: tmp_path / "missing")
    monkeypatch.setattr(token_counter.tiktoken, "get_encoding", fake_get_encoding)

    assert token_counter._load_encoding(allow_download=False) is None
    assert called is False


def test_encoding_loader_allows_explicit_download(monkeypatch, tmp_path: Path) -> None:
    sentinel = object()
    monkeypatch.setattr(token_counter, "_encoding_cache_path", lambda: tmp_path / "missing")
    monkeypatch.setattr(token_counter.tiktoken, "get_encoding", lambda name: sentinel)

    assert token_counter._load_encoding(allow_download=True) is sentinel
