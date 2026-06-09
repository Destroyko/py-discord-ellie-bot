"""Random GIF selection from a directory."""

from __future__ import annotations

import random
from pathlib import Path


class GifPool:
    """Pick a random ``.gif`` file from a directory (case-insensitive)."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory

    def list_gifs(self) -> list[Path]:
        """Return sorted paths to ``.gif`` files in the pool directory."""
        if not self._directory.is_dir():
            return []
        return sorted(
            path
            for path in self._directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".gif"
        )

    def pick_random(self) -> Path | None:
        """Return a random GIF path, or ``None`` if the pool is empty."""
        gifs = self.list_gifs()
        if not gifs:
            return None
        return random.choice(gifs)
