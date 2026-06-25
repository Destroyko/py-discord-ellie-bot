"""Load media channel cleanup configuration from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config_loader import PROJECT_ROOT
from core.exceptions import ConfigError

DEFAULT_MEDIA_CLEANUP_PATH = PROJECT_ROOT / "config" / "media_cleanup.yaml"


@dataclass(frozen=True)
class MediaCleanupConfig:
    """Runtime settings for the media channel text cleanup module."""

    enabled: bool
    channel_ids: tuple[int, ...]
    idle_threshold_minutes: int
    purge_limit: int
    text_search_limit: int


def _positive_int(data: dict, key: str, default: int) -> int:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"media_cleanup.yaml: {key} must be a positive integer")
    return value


def _parse_channel_ids(raw: object) -> tuple[int, ...]:
    if not isinstance(raw, list):
        raise ConfigError("media_cleanup.yaml: channel_ids must be a list")
    channel_ids: list[int] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, int) or isinstance(item, bool):
            raise ConfigError("media_cleanup.yaml: each channel_id must be an integer")
        if item in seen:
            raise ConfigError(f"media_cleanup.yaml: duplicate channel_id {item}")
        seen.add(item)
        channel_ids.append(item)
    return tuple(channel_ids)


def load_media_cleanup_config(
    config_path: Path | None = None,
) -> MediaCleanupConfig:
    """
    Load media cleanup settings.

    If the config file is missing, returns a disabled config.
    """
    cfg_file = config_path or DEFAULT_MEDIA_CLEANUP_PATH
    if not cfg_file.is_file():
        return MediaCleanupConfig(
            enabled=False,
            channel_ids=(),
            idle_threshold_minutes=30,
            purge_limit=10000,
            text_search_limit=1000,
        )

    with cfg_file.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("media_cleanup.yaml: enabled must be a boolean")

    channel_ids = _parse_channel_ids(raw.get("channel_ids", []))
    idle_threshold_minutes = _positive_int(raw, "idle_threshold_minutes", 30)
    purge_limit = _positive_int(raw, "purge_limit", 10000)
    text_search_limit = _positive_int(raw, "text_search_limit", 1000)

    if enabled and not channel_ids:
        raise ConfigError(
            "media_cleanup.yaml: channel_ids must contain at least one ID when enabled"
        )

    return MediaCleanupConfig(
        enabled=enabled,
        channel_ids=channel_ids,
        idle_threshold_minutes=idle_threshold_minutes,
        purge_limit=purge_limit,
        text_search_limit=text_search_limit,
    )
