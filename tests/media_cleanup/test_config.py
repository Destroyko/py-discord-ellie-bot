"""Tests for media_cleanup.yaml loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.exceptions import ConfigError
from modules.media_cleanup.config import MediaCleanupConfig, load_media_cleanup_config


def test_missing_file_returns_disabled(tmp_path: Path) -> None:
    config = load_media_cleanup_config(tmp_path / "missing.yaml")
    assert config == MediaCleanupConfig(
        enabled=False,
        channel_ids=(),
        idle_threshold_minutes=30,
        purge_limit=10000,
        text_search_limit=1000,
    )


def test_loads_enabled_config(tmp_path: Path) -> None:
    cfg = tmp_path / "media_cleanup.yaml"
    cfg.write_text(
        """
enabled: true
channel_ids:
  - 111
  - 222
idle_threshold_minutes: 45
purge_limit: 500
text_search_limit: 200
""".strip(),
        encoding="utf-8",
    )

    config = load_media_cleanup_config(cfg)
    assert config.enabled is True
    assert config.channel_ids == (111, 222)
    assert config.idle_threshold_minutes == 45
    assert config.purge_limit == 500
    assert config.text_search_limit == 200


def test_enabled_without_channels_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "media_cleanup.yaml"
    cfg.write_text("enabled: true\nchannel_ids: []\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="channel_ids"):
        load_media_cleanup_config(cfg)


def test_duplicate_channel_ids_raise(tmp_path: Path) -> None:
    cfg = tmp_path / "media_cleanup.yaml"
    cfg.write_text(
        "enabled: true\nchannel_ids: [1, 1]\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate"):
        load_media_cleanup_config(cfg)
