"""Tests for GIF pool selection."""

from __future__ import annotations

from pathlib import Path

from modules.mention_gif.gif_pool import GifPool


def test_empty_directory_returns_none(tmp_path: Path) -> None:
    pool = GifPool(tmp_path)
    assert pool.pick_random() is None


def test_missing_directory_returns_none(tmp_path: Path) -> None:
    pool = GifPool(tmp_path / "missing")
    assert pool.pick_random() is None


def test_pick_random_from_gifs(tmp_path: Path) -> None:
    (tmp_path / "a.gif").write_bytes(b"gif1")
    (tmp_path / "b.GIF").write_bytes(b"gif2")
    pool = GifPool(tmp_path)
    picked = pool.pick_random()
    assert picked is not None
    assert picked.suffix.lower() == ".gif"
    assert picked in pool.list_gifs()
